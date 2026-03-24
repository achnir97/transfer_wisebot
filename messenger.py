"""
messenger.py — Facebook Messenger webhook
==========================================
Mount this into web.py under /messenger

Meta sends all events to POST /messenger/webhook
Meta verifies webhook via GET /messenger/webhook

Environment variables required:
  MESSENGER_PAGE_TOKEN      — Page Access Token from Meta dashboard
  MESSENGER_VERIFY_TOKEN    — Any string you choose (webhook verification)
  MESSENGER_APP_SECRET      — App Secret (for payload signature verification)
"""

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse

from handler_core import handle_message, BridgeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messenger")

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


# ── Webhook verification ──────────────────────────────────

@router.get("/webhook")
async def verify_webhook(request: Request):
    """Messenger webhook verification — same pattern as WhatsApp."""
    params      = request.query_params
    mode        = params.get("hub.mode")
    token       = params.get("hub.verify_token")
    challenge   = params.get("hub.challenge")

    expected = os.getenv("MESSENGER_VERIFY_TOKEN", "bridge_messenger_2026")
    if mode == "subscribe" and token == expected:
        logger.info("Messenger webhook verified ✅")
        return PlainTextResponse(challenge)

    logger.warning("Messenger webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Incoming message handler ──────────────────────────────

@router.post("/webhook")
async def receive_message(request: Request, x_hub_signature_256: str = Header(default="")):
    """
    Receive incoming Messenger messages.
    Verifies signature if MESSENGER_APP_SECRET is set.
    """
    body = await request.body()

    # Verify payload signature (recommended for production)
    app_secret = os.getenv("MESSENGER_APP_SECRET", "")
    if app_secret and x_hub_signature_256:
        expected_sig = "sha256=" + hmac.new(
            app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, x_hub_signature_256):
            logger.warning("Messenger: invalid signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        # Messenger wraps in object/entry arrays
        if data.get("object") != "page":
            return {"status": "ok"}

        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                await _process_event(event)

    except Exception as e:
        logger.error(f"Messenger webhook error: {e}", exc_info=True)

    return {"status": "ok"}


async def _process_event(event: dict) -> None:
    """Process a single Messenger messaging event."""
    sender_id = event.get("sender", {}).get("id", "")
    if not sender_id:
        return

    # Ignore our own messages (echo events)
    recipient_id = event.get("recipient", {}).get("id", "")

    # Text message
    if "message" in event:
        message = event["message"]

        # Ignore echoes
        if message.get("is_echo"):
            return

        text = message.get("text", "").strip()
        if not text:
            return

        lang = _get_user_lang(sender_id)
        logger.info(f"Messenger ← {sender_id[:8]}… | {text[:50]!r}")

        response = await handle_message(
            text=text,
            user_id=sender_id,
            platform="messenger",
            lang=lang,
        )
        await _send_response(sender_id, response)

    # Postback (button tap)
    elif "postback" in event:
        payload = event["postback"].get("payload", "")
        title   = event["postback"].get("title", "")
        text    = title or payload

        lang = _get_user_lang(sender_id)
        logger.info(f"Messenger postback ← {sender_id[:8]}… | {payload!r}")

        response = await handle_message(
            text=text,
            user_id=sender_id,
            platform="messenger",
            lang=lang,
        )
        await _send_response(sender_id, response)


# ── Send response helpers ─────────────────────────────────

async def _send_response(to: str, response: BridgeResponse) -> None:
    """
    Send BridgeResponse to Messenger user.
    
    Messenger supports rich buttons natively — much easier than WhatsApp.
    """
    page_token = os.getenv("MESSENGER_PAGE_TOKEN", "")
    if not page_token:
        logger.error("MESSENGER_PAGE_TOKEN not set")
        return

    url     = f"{GRAPH_API_BASE}/me/messages"
    params  = {"access_token": page_token}
    headers = {"Content-Type": "application/json"}

    clean_text = response.text  # Messenger renders markdown-like text fine

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            # Case 1: URL buttons (Send Here referral links)
            if response.buttons:
                # Messenger generic template with URL buttons
                elements = [{
                    "title": "Bridge — Best Rate",
                    "subtitle": clean_text[:80],
                    "buttons": [
                        {
                            "type": "web_url",
                            "url": btn.url,
                            "title": btn.label[:20],
                        }
                        for btn in response.buttons[:3]
                        if btn.url
                    ],
                }]

                # First send the comparison text
                await client.post(url, params=params, headers=headers, json={
                    "recipient": {"id": to},
                    "message": {"text": _truncate(clean_text, 2000)},
                })

                # Then send the action buttons as a template
                await client.post(url, params=params, headers=headers, json={
                    "recipient": {"id": to},
                    "message": {
                        "attachment": {
                            "type": "template",
                            "payload": {
                                "template_type": "generic",
                                "elements": elements,
                            },
                        }
                    },
                })

            # Case 2: Quick replies
            elif response.quick_replies:
                quick_replies = [
                    {
                        "content_type": "text",
                        "title": qr[:20],
                        "payload": qr.upper().replace(" ", "_"),
                    }
                    for qr in response.quick_replies[:13]  # Messenger max 13
                ]
                await client.post(url, params=params, headers=headers, json={
                    "recipient": {"id": to},
                    "message": {
                        "text": _truncate(clean_text, 2000),
                        "quick_replies": quick_replies,
                    },
                })

            # Case 3: Plain text (chunk if needed)
            else:
                for chunk in _chunk_text(clean_text, 2000):
                    await client.post(url, params=params, headers=headers, json={
                        "recipient": {"id": to},
                        "message": {"text": chunk},
                    })

    except Exception as e:
        logger.error(f"Messenger send error to {to}: {e}")


# ── Language detection ────────────────────────────────────

_messenger_langs: dict[str, str] = {}

def _get_user_lang(sender_id: str) -> str:
    return _messenger_langs.get(sender_id, "en")

def set_user_lang(sender_id: str, lang: str) -> None:
    _messenger_langs[sender_id] = lang


# ── Helpers ───────────────────────────────────────────────

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."

def _chunk_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks