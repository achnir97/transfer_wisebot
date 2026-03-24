"""
whatsapp.py — WhatsApp Cloud API webhook
=========================================
Mount this into web.py under /whatsapp

Meta sends all events to POST /whatsapp/webhook
Meta verifies webhook via GET /whatsapp/webhook

Environment variables required:
  WHATSAPP_TOKEN          — Permanent access token from Meta
  WHATSAPP_PHONE_ID       — Phone Number ID from Meta dashboard
  WHATSAPP_VERIFY_TOKEN   — Any string you choose (used once for webhook verification)
"""

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse

from handler_core import handle_message, BridgeResponse, LANGUAGES, CURRENCIES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp")

WHATSAPP_API_VERSION = "v18.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


# ── Webhook verification (called once by Meta when you set up webhook) ────

@router.get("/webhook")
async def verify_webhook(request: Request):
    """
    Meta sends a GET request to verify the webhook URL.
    Must respond with hub.challenge if hub.verify_token matches.
    """
    params = request.query_params
    mode        = params.get("hub.mode")
    token       = params.get("hub.verify_token")
    challenge   = params.get("hub.challenge")

    expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "bridge_verify_2026")
    if mode == "subscribe" and token == expected:
        logger.info("WhatsApp webhook verified ✅")
        return PlainTextResponse(challenge)

    logger.warning(f"WhatsApp webhook verification failed | mode={mode} | token={token}")
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Incoming message handler ──────────────────────────────

@router.post("/webhook")
async def receive_message(request: Request):
    """
    Receive incoming WhatsApp messages from Meta.
    All user-initiated messages are free (service conversations).
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Meta wraps everything in entry/changes arrays
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Handle incoming messages
                for message in value.get("messages", []):
                    await _process_message(message, value)

                # Handle message status updates (delivered, read) — just log
                for status in value.get("statuses", []):
                    logger.debug(f"WhatsApp status: {status.get('status')} | id={status.get('id')}")

    except Exception as e:
        logger.error(f"WhatsApp webhook processing error: {e}", exc_info=True)

    # Always return 200 — Meta retries if it doesn't get 200
    return {"status": "ok"}


async def _process_message(message: dict, value: dict) -> None:
    """Extract text from a WhatsApp message and generate a Bridge response."""
    msg_type = message.get("type")
    from_number = message.get("from", "")  # E.164 format: "821012345678"

    if not from_number:
        return

    # Extract text (handle text, button replies, and list replies)
    if msg_type == "text":
        text = message.get("text", {}).get("body", "").strip()
    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        # Button reply
        if interactive.get("type") == "button_reply":
            text = interactive["button_reply"].get("title", "")
        # List reply
        elif interactive.get("type") == "list_reply":
            text = interactive["list_reply"].get("title", "")
        else:
            text = ""
    else:
        # Ignore audio, image, video, etc. for now
        logger.debug(f"WhatsApp: ignoring message type={msg_type}")
        return

    if not text:
        return

    # Detect language from profile or default to English
    # (WhatsApp doesn't send locale, so we start English and user can change)
    lang = _get_user_lang(from_number)

    logger.info(f"WhatsApp ← {from_number[:6]}… | {text[:50]!r}")

    # Call shared handler
    response = await handle_message(
        text=text,
        user_id=from_number,
        platform="whatsapp",
        lang=lang,
    )

    # Send response back
    await _send_response(from_number, response)

    # Mark message as read
    await _mark_read(message.get("id", ""))


# ── Send response helpers ─────────────────────────────────

async def _send_response(to: str, response: BridgeResponse) -> None:
    """
    Send a BridgeResponse back to the WhatsApp user.
    
    If response has buttons → send interactive button message (up to 3 buttons)
    If response has quick_replies → send interactive list message  
    Otherwise → plain text
    """
    phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
    token    = os.getenv("WHATSAPP_TOKEN", "")

    if not phone_id or not token:
        logger.error("WHATSAPP_PHONE_ID or WHATSAPP_TOKEN not set")
        return

    url     = f"{GRAPH_API_BASE}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Strip markdown formatting that WhatsApp doesn't support the same way
    clean_text = _strip_markdown(response.text)

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            # Case 1: URL buttons (Send Here links) — use interactive CTA buttons
            if response.buttons:
                # WhatsApp supports max 3 buttons; use CTA URL buttons for external links
                # For more than 3 send multiple messages or use list
                btns = response.buttons[:3]

                # If buttons have URLs, send as text + separate URL messages
                # (WhatsApp interactive URL buttons require template approval for some cases)
                # Safest: send text first, then send each URL as a separate message
                await client.post(url, headers=headers, json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": clean_text, "preview_url": False},
                })

                # Send each referral link as a separate message
                for btn in btns:
                    if btn.url:
                        await client.post(url, headers=headers, json={
                            "messaging_product": "whatsapp",
                            "to": to,
                            "type": "text",
                            "text": {"body": f"🔗 {btn.label}\n{btn.url}", "preview_url": False},
                        })

            # Case 2: Quick replies (menu options) — use interactive button message
            elif response.quick_replies and len(response.quick_replies) <= 3:
                buttons = [
                    {"type": "reply", "reply": {"id": f"qr_{i}", "title": qr[:20]}}
                    for i, qr in enumerate(response.quick_replies[:3])
                ]
                await client.post(url, headers=headers, json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": clean_text[:1024]},
                        "action": {"buttons": buttons},
                    },
                })

            # Case 3: Many quick replies → list message
            elif response.quick_replies and len(response.quick_replies) > 3:
                rows = [
                    {"id": f"qr_{i}", "title": qr[:24]}
                    for i, qr in enumerate(response.quick_replies[:10])
                ]
                await client.post(url, headers=headers, json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "body": {"text": clean_text[:1024]},
                        "action": {
                            "button": "Choose ▾",
                            "sections": [{"title": "Options", "rows": rows}],
                        },
                    },
                })

            # Case 4: Plain text
            else:
                # WhatsApp max message length is 4096
                chunks = _chunk_text(clean_text, 4096)
                for chunk in chunks:
                    await client.post(url, headers=headers, json={
                        "messaging_product": "whatsapp",
                        "to": to,
                        "type": "text",
                        "text": {"body": chunk, "preview_url": False},
                    })

    except Exception as e:
        logger.error(f"WhatsApp send error to {to}: {e}")


async def _mark_read(message_id: str) -> None:
    """Mark a message as read (shows double blue ticks to sender)."""
    if not message_id:
        return
    phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
    token    = os.getenv("WHATSAPP_TOKEN", "")
    if not phone_id or not token:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{GRAPH_API_BASE}/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
            )
    except Exception:
        pass  # Non-critical


# ── Language detection ────────────────────────────────────

# Simple in-memory store: whatsapp_number → lang
_wa_user_langs: dict[str, str] = {}

def _get_user_lang(phone: str) -> str:
    return _wa_user_langs.get(phone, "en")

def set_user_lang(phone: str, lang: str) -> None:
    _wa_user_langs[phone] = lang


# ── Text helpers ──────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """
    Convert Telegram-style Markdown to plain text for WhatsApp.
    WhatsApp supports *bold* and _italic_ natively but not headers etc.
    """
    import re
    # Keep *bold* as-is (WhatsApp supports it)
    # Remove backtick code blocks
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove leading # headers
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    return text.strip()


def _chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks of max_len characters."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks