"""
handler_core.py — Platform-agnostic Bridge message handler
===========================================================
Single brain for Telegram, WhatsApp, and Facebook Messenger.

Every platform calls:
    result = await handle_message(text, user_id, platform, lang)

Returns a BridgeResponse with text + optional buttons.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from rates import get_live_rates, format_comparison
from users import save_user, get_user, update_user, increment_comparison, log_user_click, save_alert, get_user_alerts, get_all_alerts
from referral import generate_referral_link, log_click

logger = logging.getLogger(__name__)

# ── Language & currency maps ──────────────────────────────
LANGUAGES = {
    "ne": "🇳🇵 नेपाली",
    "vi": "🇻🇳 Tiếng Việt",
    "en": "🇬🇧 English",
    "tl": "🇵🇭 Tagalog",
    "id": "🇮🇩 Bahasa Indonesia",
    "uz": "🇺🇿 O'zbek",
    "th": "🇹🇭 ภาษาไทย",
    "zh": "🇨🇳 中文",
}

CURRENCIES = {
    "ne": "NPR", "vi": "VND", "tl": "PHP",
    "id": "IDR", "uz": "UZS", "en": "USD",
    "th": "THB", "zh": "CNY",
}

# Detect language from message text keywords
LANG_KEYWORDS = {
    "ne": ["पठाउ", "दर", "नेपाल", "NPR", "compare", "सुरु"],
    "vi": ["gửi", "tiền", "tỷ giá", "VND"],
    "tl": ["padala", "pera", "PHP", "magpadala"],
    "id": ["kirim", "uang", "IDR", "kurs"],
}

# ── Translations ──────────────────────────────────────────
T = {
    "welcome": {
        "ne": (
            "नमस्ते! 🙏 म *Bridge* हुँ।\n\n"
            "कोरियाबाट घर पैसा पठाउन सबैभन्दा राम्रो दर खोज्नुस् 💰\n\n"
            "तलको विकल्प छान्नुस्:"
        ),
        "en": (
            "Hello! 🙏 I'm *Bridge*.\n\n"
            "Find the best rate to send money from Korea 💰\n\n"
            "Choose an option below:"
        ),
        "vi": (
            "Xin chào! 🙏 Tôi là *Bridge*.\n\n"
            "Tìm tỷ giá tốt nhất để gửi tiền từ Hàn Quốc 💰\n\n"
            "Chọn một tùy chọn bên dưới:"
        ),
        "tl": (
            "Kumusta! 🙏 Ako si *Bridge*.\n\n"
            "Hanapin ang pinakamahusay na rate para magpadala mula Korea 💰\n\n"
            "Pumili ng opsyon sa ibaba:"
        ),
        "id": (
            "Halo! 🙏 Saya *Bridge*.\n\n"
            "Temukan nilai tukar terbaik untuk mengirim uang dari Korea 💰\n\n"
            "Pilih opsi di bawah:"
        ),
        "uz": "Salom! 🙏 Men *Bridge* man.\n\nKoreadan pul yuborishning eng yaxshi kursini toping 💰",
        "th": "สวัสดี! 🙏 ผมคือ *Bridge*\n\nค้นหาอัตราแลกเปลี่ยนที่ดีที่สุดสำหรับส่งเงินจากเกาหลี 💰",
        "zh": "你好！🙏 我是 *Bridge*。\n\n从韩国以最佳汇率汇款 💰",
    },
    "ask_amount": {
        "ne": "₩ कति पठाउन चाहनुहुन्छ? (KRW मा)\n\nउदाहरण: *500000*",
        "en": "₩ How much do you want to send? (in KRW)\n\nExample: *500000*",
        "vi": "₩ Bạn muốn gửi bao nhiêu? (KRW)\n\nVí dụ: *500000*",
        "tl": "₩ Magkano ang gusto mong ipadala? (KRW)\n\nHalimbawa: *500000*",
        "id": "₩ Berapa yang ingin Anda kirim? (dalam KRW)\n\nContoh: *500000*",
        "uz": "₩ Qancha pul yubormoqchisiz? (KRW da)\n\nMisol: *500000*",
        "th": "₩ คุณต้องการส่งเงินเท่าไหร่? (KRW)\n\nตัวอย่าง: *500000*",
        "zh": "₩ 您想汇多少钱？\n\n示例：*500000*",
    },
    "comparing": {
        "ne": "⏳ दर खोज्दैछु...",
        "en": "⏳ Fetching live rates...",
        "vi": "⏳ Đang tìm tỷ giá...",
        "tl": "⏳ Kinukuha ang mga rate...",
        "id": "⏳ Mengambil kurs...",
        "uz": "⏳ Kurslar olinmoqda...",
        "th": "⏳ กำลังดึงอัตราแลกเปลี่ยน...",
        "zh": "⏳ 正在获取实时汇率...",
    },
    "rate_error": {
        "ne": "⚠️ दर लोड गर्न सकिएन। कृपया फेरि प्रयास गर्नुस्।",
        "en": "⚠️ Could not load rates. Please try again.",
        "vi": "⚠️ Không thể tải tỷ giá. Vui lòng thử lại.",
        "tl": "⚠️ Hindi ma-load ang mga rate. Subukan ulit.",
        "id": "⚠️ Tidak dapat memuat kurs. Coba lagi.",
        "uz": "⚠️ Kurslarni yuklab bo'lmadi.",
        "th": "⚠️ ไม่สามารถโหลดอัตราได้",
        "zh": "⚠️ 无法加载汇率，请重试。",
    },
    "help": {
        "ne": (
            "📖 *Bridge Bot सहयोग*\n\n"
            "• *compare* — दर तुलना गर्न\n"
            "• *rates* — हालको दर हेर्न\n"
            "• *alert* — दर अलर्ट सेट गर्न\n"
            "• *help* — यो सन्देश\n\n"
            "✅ Bridge ले तपाईंको पैसा छुँदैन।\n\n"
            "Telegram मा पनि पाउनुहुन्छ: @BridgeKoreaBot"
        ),
        "en": (
            "📖 *Bridge Bot Help*\n\n"
            "• *compare* — Compare rates\n"
            "• *rates* — See current rates\n"
            "• *alert* — Set a rate alert\n"
            "• *help* — This message\n\n"
            "✅ Bridge never touches your money.\n\n"
            "Also available on Telegram: @BridgeKoreaBot"
        ),
        "vi": (
            "📖 *Bridge Bot Trợ giúp*\n\n"
            "• *compare* — So sánh tỷ giá\n"
            "• *rates* — Xem tỷ giá\n"
            "• *help* — Tin nhắn này\n\n"
            "✅ Bridge không bao giờ chạm vào tiền của bạn."
        ),
        "tl": (
            "📖 *Bridge Bot Tulong*\n\n"
            "• *compare* — Ikumpara ang mga rate\n"
            "• *rates* — Tingnan ang rates\n"
            "• *help* — Mensaheng ito\n\n"
            "✅ Hindi hahawakan ng Bridge ang iyong pera."
        ),
        "id": (
            "📖 *Bridge Bot Bantuan*\n\n"
            "• *compare* — Bandingkan kurs\n"
            "• *rates* — Lihat kurs\n"
            "• *help* — Pesan ini\n\n"
            "✅ Bridge tidak pernah menyentuh uang Anda."
        ),
        "uz": "📖 *Bridge Bot*\n\n• *compare* — Kurslarni solishtirish\n• *rates* — Kurslarni ko'rish\n• *help* — Yordam",
        "th": "📖 *Bridge Bot*\n\n• *compare* — เปรียบเทียบอัตรา\n• *rates* — ดูอัตรา\n• *help* — ช่วยเหลือ",
        "zh": "📖 *Bridge Bot*\n\n• *compare* — 比较汇率\n• *rates* — 查看汇率\n• *help* — 帮助",
    },
    "language_prompt": {
        "ne": "🌐 भाषा छान्नुस्:",
        "en": "🌐 Choose your language:",
        "vi": "🌐 Chọn ngôn ngữ:",
        "tl": "🌐 Pumili ng wika:",
        "id": "🌐 Pilih bahasa:",
        "uz": "🌐 Tilni tanlang:",
        "th": "🌐 เลือกภาษา:",
        "zh": "🌐 选择语言：",
    },
    "alert_ask": {
        "ne": "🔔 कुन दरमा सूचना चाहनुहुन्छ?\n\nहालको दर: 1 KRW = {rate:.5f} {currency}\n\nउदाहरण: *{suggested}*",
        "en": "🔔 What rate do you want an alert for?\n\nCurrent best: 1 KRW = {rate:.5f} {currency}\n\nExample: *{suggested}*",
        "vi": "🔔 Tỷ giá mục tiêu?\n\nHiện tại: 1 KRW = {rate:.5f} {currency}\n\nVí dụ: *{suggested}*",
        "tl": "🔔 Anong rate ang gusto mong alerto?\n\nKasalukuyan: 1 KRW = {rate:.5f} {currency}\n\nHalimbawa: *{suggested}*",
        "id": "🔔 Target kurs Anda?\n\nSaat ini: 1 KRW = {rate:.5f} {currency}\n\nContoh: *{suggested}*",
        "uz": "🔔 Maqsadli kurs?\n\nHozir: 1 KRW = {rate:.5f} {currency}\n\nMisol: *{suggested}*",
        "th": "🔔 อัตราเป้าหมาย?\n\nปัจจุบัน: 1 KRW = {rate:.5f} {currency}\n\nตัวอย่าง: *{suggested}*",
        "zh": "🔔 目标汇率?\n\n当前: 1 KRW = {rate:.5f} {currency}\n\n示例: *{suggested}*",
    },
    "alert_confirm": {
        "ne": "✅ अलर्ट सेट!\n\n1 KRW = *{rate}* {currency} पुग्दा सूचित गर्छु। 🔔",
        "en": "✅ Alert set!\n\nI'll notify you when 1 KRW = *{rate}* {currency}. 🔔",
        "vi": "✅ Đã đặt cảnh báo!\n\nThông báo khi 1 KRW = *{rate}* {currency}. 🔔",
        "tl": "✅ Alert set!\n\nAbisuhan kita kapag 1 KRW = *{rate}* {currency}. 🔔",
        "id": "✅ Peringatan diatur!\n\nAnda akan diberitahu ketika 1 KRW = *{rate}* {currency}. 🔔",
        "uz": "✅ Ogohlantirish o'rnatildi!\n\n1 KRW = *{rate}* {currency} bo'lganda xabar. 🔔",
        "th": "✅ ตั้งการแจ้งเตือน!\n\nแจ้งเมื่อ 1 KRW = *{rate}* {currency} 🔔",
        "zh": "✅ 提醒已设置!\n\n当 1 KRW = *{rate}* {currency} 时通知您。🔔",
    },
    "amount_too_low":  {"ne": "❌ न्यूनतम ₩10,000", "en": "❌ Minimum ₩10,000", "vi": "❌ Tối thiểu ₩10,000", "tl": "❌ Minimum ₩10,000", "id": "❌ Minimum ₩10,000", "uz": "❌ Minimal ₩10,000", "th": "❌ ขั้นต่ำ ₩10,000", "zh": "❌ 最低 ₩10,000"},
    "amount_too_high": {"ne": "❌ अधिकतम ₩5,000,000", "en": "❌ Maximum ₩5,000,000", "vi": "❌ Tối đa ₩5,000,000", "tl": "❌ Maximum ₩5,000,000", "id": "❌ Maksimum ₩5,000,000", "uz": "❌ Maksimal ₩5,000,000", "th": "❌ สูงสุด ₩5,000,000", "zh": "❌ 最高 ₩5,000,000"},
}

def _t(key: str, lang: str) -> str:
    return T.get(key, {}).get(lang) or T.get(key, {}).get("en", key)


# ── Response dataclass ────────────────────────────────────

@dataclass
class Button:
    label: str
    url: Optional[str] = None       # External link (Send Here)
    payload: Optional[str] = None   # Internal action (postback)

@dataclass
class BridgeResponse:
    text: str
    buttons: list[Button] = field(default_factory=list)
    quick_replies: list[str] = field(default_factory=list)  # language picker etc.


# ── State store (Supabase-backed for scalability) ─────────
# Falls back to in-memory if DB unavailable

_state_cache: dict[str, dict] = {}   # local cache to avoid redundant DB reads

def _state_key(platform: str, user_id: str) -> str:
    return f"{platform}:{user_id}"

def _get_state(platform: str, user_id: str) -> dict:
    key = _state_key(platform, user_id)
    if key in _state_cache:
        return _state_cache[key]
    try:
        uid_int = int(user_id) if user_id.isdigit() else 0
        if uid_int:
            from db import get_db
            res = get_db().table("users").select("state,state_data").eq("user_id", uid_int).execute()
            if res.data and res.data[0].get("state"):
                s = {"state": res.data[0]["state"], "data": res.data[0].get("state_data") or {}}
                _state_cache[key] = s
                return s
    except Exception:
        pass
    return {"state": "idle", "data": {}}

def _set_state(platform: str, user_id: str, state: str, data: dict = None) -> None:
    key = _state_key(platform, user_id)
    val = {"state": state, "data": data or {}}
    _state_cache[key] = val
    try:
        uid_int = int(user_id) if user_id.isdigit() else 0
        if uid_int:
            from db import get_db
            get_db().table("users").update({"state": state, "state_data": data or {}}).eq("user_id", uid_int).execute()
    except Exception:
        pass

def _clear_state(platform: str, user_id: str) -> None:
    key = _state_key(platform, user_id)
    _state_cache.pop(key, None)
    try:
        uid_int = int(user_id) if user_id.isdigit() else 0
        if uid_int:
            from db import get_db
            get_db().table("users").update({"state": None, "state_data": None}).eq("user_id", uid_int).execute()
    except Exception:
        pass


# ── Main handler ──────────────────────────────────────────

async def handle_message(
    text: str,
    user_id: str,
    platform: str,          # "whatsapp" | "messenger" | "telegram"
    lang: str = "en",
    user_name: str = "",
) -> BridgeResponse:
    """
    Core message handler. Platform-agnostic.
    Returns BridgeResponse with text + optional buttons.
    """
    text_clean  = text.strip().lower() if text else ""
    state_data  = _get_state(platform, user_id)
    state       = state_data["state"]
    currency    = CURRENCIES.get(lang, "NPR")

    logger.info(f"[{platform}] user={user_id} state={state} text={text[:40]!r}")

    # ── Save/update user on every message ─────────────────
    uid_int = int(user_id) if user_id.isdigit() else 0
    if uid_int:
        existing = get_user(uid_int)
        if existing:
            lang     = existing.get("language", lang)
            currency = existing.get("currency", currency)
        else:
            save_user(uid_int, user_name or None, None, lang, currency)
            update_user(uid_int, {"platform": platform})

    # ── State: waiting for alert rate ─────────────────────
    if state == "awaiting_alert_rate":
        return await _handle_alert_rate_input(text_clean, user_id, platform, lang, currency, state_data["data"])

    # ── Greetings / start ─────────────────────────────────
    if text_clean in ("start", "/start", "hi", "hello", "안녕", "नमस्ते", "xin chào", "halo", "kumusta", "salom"):
        existing = get_user(int(user_id) if user_id.isdigit() else 0)
        if existing:
            lang = existing.get("language", lang)
            currency = existing.get("currency", currency)
        return BridgeResponse(
            text=_t("welcome", lang),
            quick_replies=["💸 Compare Rates", "📊 Show Rates", "🔔 Set Alert", "🌐 Language"],
        )

    # ── Help ──────────────────────────────────────────────
    if text_clean in ("help", "/help", "सहयोग", "trợ giúp", "bantuan", "tulong", "yordam", "ช่วย", "帮助"):
        return BridgeResponse(text=_t("help", lang))

    # ── Language change ───────────────────────────────────
    if text_clean in ("language", "lang", "भाषा", "/language", "🌐 language"):
        _set_state(platform, user_id, "choosing_language")
        lang_list = "\n".join([
            f"{i+1}️⃣ {v}" for i, v in enumerate(LANGUAGES.values())
        ])
        return BridgeResponse(
            text=f"🌐 Choose your language:\n\n{lang_list}\n\nReply with the number or name.",
            quick_replies=list(LANGUAGES.values())[:3] + ["More →"],
        )

    # ── Check if user replied with a language number or name ──
    lang_items = list(LANGUAGES.items())
    matched_lang = None
    # Match by number (1-8)
    if text_clean.strip() in [str(i+1) for i in range(len(lang_items))]:
        idx = int(text_clean.strip()) - 1
        matched_lang = lang_items[idx]
    else:
        # Match by emoji+name or just name
        for code, label in lang_items:
            if text.strip() in (label, label.split(" ", 1)[-1].strip()):
                matched_lang = (code, label)
                break
    if matched_lang:
        code, label = matched_lang
        new_currency = CURRENCIES.get(code, "NPR")
        _update_user_lang(user_id, platform, code, new_currency)
        _clear_state(platform, user_id)
        return BridgeResponse(
            text=f"✅ Language set to {label}\n\n" + _t("welcome", code),
            quick_replies=["💸 Compare Rates", "📊 Show Rates", "🔔 Set Alert", "🌐 Language"],
        )

    # ── New Amount (after comparison) ─────────────────────
    if text_clean in ("🔄 new amount", "new amount", "compare again"):
        _set_state(platform, user_id, "awaiting_amount", {"lang": lang, "currency": currency})
        return BridgeResponse(text=_t("ask_amount", lang))

    # ── More languages ────────────────────────────────────
    if text_clean in ("more →", "more", "more languages"):
        lang_list = "\n".join([
            f"{i+1}️⃣ {v}" for i, v in enumerate(LANGUAGES.values())
        ])
        return BridgeResponse(
            text=f"🌐 Choose your language:\n\n{lang_list}\n\nReply with the number or name.",
            quick_replies=list(LANGUAGES.values())[3:],
        )

    # ── Alert setup ───────────────────────────────────────
    if text_clean in ("alert", "/alert", "🔔 set alert", "अलर्ट", "cảnh báo", "peringatan", "ogohlantirish", "แจ้งเตือน", "提醒"):
        return await _start_alert(user_id, platform, lang, currency)

    # ── Rates only (no amount) ────────────────────────────
    if text_clean in ("rates", "/rates", "📊 show rates", "दरहरू", "tỷ giá", "kurs", "อัตรา", "汇率"):
        return await _do_rates_only(lang, currency)

    # ── Compare / send money ──────────────────────────────
    if text_clean in ("compare", "/send", "💸 compare rates", "compare rates", "send", "पैसा पठाउनुस्", "gửi tiền", "kirim uang", "magpadala"):
        _set_state(platform, user_id, "awaiting_amount", {"lang": lang, "currency": currency})
        return BridgeResponse(text=_t("ask_amount", lang))

    # ── Numeric input → comparison ────────────────────────
    amount = _parse_amount(text_clean)
    if amount is not None:
        if state == "awaiting_amount":
            _clear_state(platform, user_id)
        return await _do_comparison(amount, user_id, platform, lang, currency)

    # ── Fallback ──────────────────────────────────────────
    return BridgeResponse(
        text=_t("welcome", lang),
        quick_replies=["💸 Compare Rates", "📊 Show Rates", "🔔 Set Alert", "🌐 Language"],
    )


# ── Alert flow ────────────────────────────────────────────

async def _start_alert(user_id: str, platform: str, lang: str, currency: str) -> BridgeResponse:
    rates = await get_live_rates("KRW", currency)
    if not rates:
        return BridgeResponse(text=_t("rate_error", lang))
    best      = max(rates, key=lambda x: x["rate"])["rate"]
    suggested = round(best * 1.02, 5)
    _set_state(platform, user_id, "awaiting_alert_rate", {"lang": lang, "currency": currency})
    return BridgeResponse(
        text=_t("alert_ask", lang).format(rate=best, currency=currency, suggested=suggested),
    )


async def _handle_alert_rate_input(
    text: str, user_id: str, platform: str, lang: str, currency: str, state_ctx: dict
) -> BridgeResponse:
    lang     = state_ctx.get("lang", lang)
    currency = state_ctx.get("currency", currency)
    try:
        target = float(text.replace(",", "").strip())
        if target <= 0:
            raise ValueError
    except ValueError:
        return BridgeResponse(text="❌ Please enter a valid number. Example: 0.108")

    uid_int = int(user_id) if user_id.isdigit() else 0
    save_alert(user_id=uid_int, currency=currency, target_rate=target, lang=lang)
    _clear_state(platform, user_id)

    return BridgeResponse(
        text=_t("alert_confirm", lang).format(rate=target, currency=currency),
        quick_replies=["💸 Compare Rates", "📊 Show Rates"],
    )


# ── Rate comparison ───────────────────────────────────────

async def _do_comparison(
    amount: int, user_id: str, platform: str, lang: str, currency: str
) -> BridgeResponse:
    if amount < 10_000:
        return BridgeResponse(text=_t("amount_too_low", lang))
    if amount > 5_000_000:
        return BridgeResponse(text=_t("amount_too_high", lang))

    rates = await get_live_rates("KRW", currency)
    if not rates:
        return BridgeResponse(text=_t("rate_error", lang))

    text = format_comparison(rates, amount, currency, lang)

    # Top 3 send buttons with referral links
    uid_int = int(user_id) if user_id.isdigit() else 0
    sorted_rates = sorted(
        rates,
        key=lambda x: x["rate"] * (amount - x["fee_flat_krw"] - amount * x["fee_percent"]),
        reverse=True,
    )[:3]

    buttons = []
    for r in sorted_rates:
        ref_url = generate_referral_link(
            platform=r["platform"],
            user_id=uid_int,
            amount=amount,
            currency=currency,
        )
        label = f"Send via {r['platform']} →"
        buttons.append(Button(label=label, url=ref_url))

    # Log comparison
    try:
        increment_comparison(uid_int)
        log_click(uid_int, sorted_rates[0]["platform"], amount, currency, click_type="intent")
    except Exception:
        pass

    return BridgeResponse(
        text=text,
        buttons=buttons,
        quick_replies=["🔄 New Amount", "🔔 Set Alert", "🌐 Language"],
    )


async def _do_rates_only(lang: str, currency: str) -> BridgeResponse:
    rates = await get_live_rates("KRW", currency)
    if not rates:
        return BridgeResponse(text=_t("rate_error", lang))
    text = format_comparison(rates, 0, currency, lang, show_amounts=False)
    return BridgeResponse(
        text=text,
        quick_replies=["💸 Compare Rates", "🔔 Set Alert"],
    )


# ── Helpers ───────────────────────────────────────────────

def _parse_amount(text: str) -> Optional[int]:
    clean = re.sub(r"[₩,\s]", "", text)
    try:
        return int(float(clean))
    except (ValueError, TypeError):
        return None


def _update_user_lang(user_id: str, platform: str, lang: str, currency: str) -> None:
    uid_int = int(user_id) if user_id.isdigit() else 0
    try:
        update_user(uid_int, {"language": lang, "currency": currency, "platform": platform})
    except Exception:
        pass
    