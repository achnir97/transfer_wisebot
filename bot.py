"""
BRIDGE Telegram Bot — Complete Implementation
==============================================
AI-powered remittance comparison bot for foreign workers in South Korea.
Compares rates from IME Nepal, Wise, Hana Bank, Western Union, Remitly,
Prabhu Money.  Supports 8 languages.  Earns referral commissions.

Commands:
  /start      Welcome + language selection
  /send       Compare rates for an amount
  /rates      Current rates (no amount needed)
  /alert      Set a rate alert
  /myalerts   View / cancel your active alerts
  /language   Change language
  /help       Help message
  /cancel     Cancel current action
  /admin      Admin stats (ADMIN_USER_ID only)

Setup:
  pip install -r requirements.txt
  cp .env.example .env  && fill in your keys
  python bot.py
"""

import logging
import os
from datetime import datetime
from dotenv import load_dotenv

from handler_core import handle_message
from rates import get_live_rates, format_comparison
from users import save_user, get_user, update_user, increment_comparison, log_user_click, save_alert, get_user_alerts, get_all_alerts, remove_alert, remove_all_user_alerts, get_stats
from referral import generate_referral_link, log_click, get_referral_stats
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from rates    import get_live_rates, format_comparison, get_platforms_for_currency
from ai       import get_ai_response
from users    import (
    save_user, get_user, update_user, increment_comparison, log_user_click,
    save_alert, get_all_alerts, get_user_alerts,
    remove_alert, remove_all_user_alerts, get_stats,
)
from referral import generate_referral_link, log_click, get_referral_stats

load_dotenv()

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bridge_bot.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────
CHOOSING_LANGUAGE   = 0
ENTERING_AMOUNT     = 1
ENTERING_ALERT_RATE = 2
MAIN_MENU           = 3

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

CURRENCIES: dict[str, str] = {
    "ne": "NPR",
    "vi": "VND",
    "tl": "PHP",
    "id": "IDR",
    "uz": "UZS",
    "en": "USD",
    "th": "THB",
    "zh": "CNY",
}

# Detect Telegram locale → bot language code
_TG_LANG_MAP = {
    "ne": "ne", "vi": "vi", "tl": "tl", "fil": "tl",
    "id": "id", "uz": "uz", "th": "th", "zh": "zh",
    "zh-hans": "zh", "zh-hant": "zh",
}

# ── Multilingual button labels ────────────────────────────
BUTTONS: dict[str, dict[str, str]] = {
    "send_money": {
        "ne": "💸 पैसा पठाउनुस्", "vi": "💸 Gửi tiền",    "en": "💸 Send Money",
        "tl": "💸 Magpadala",     "id": "💸 Kirim Uang", "uz": "💸 Pul yuborish",
        "th": "💸 ส่งเงิน",       "zh": "💸 汇款",
    },
    "rates": {
        "ne": "📊 दरहरू",     "vi": "📊 Tỷ giá",    "en": "📊 Rates",
        "tl": "📊 Mga Rate", "id": "📊 Kurs",       "uz": "📊 Kurslar",
        "th": "📊 อัตราแลก",  "zh": "📊 汇率",
    },
    "alert": {
        "ne": "🔔 अलर्ट",        "vi": "🔔 Cảnh báo",       "en": "🔔 Alert",
        "tl": "🔔 Alerto",       "id": "🔔 Peringatan",    "uz": "🔔 Ogohlantirish",
        "th": "🔔 แจ้งเตือน",    "zh": "🔔 提醒",
    },
    "help": {
        "ne": "❓ सहयोग",   "vi": "❓ Trợ giúp", "en": "❓ Help",
        "tl": "❓ Tulong",  "id": "❓ Bantuan",   "uz": "❓ Yordam",
        "th": "❓ ช่วยเหลือ", "zh": "❓ 帮助",
    },
}

# Reverse map: button text → action key (for any language)
_BTN_REVERSE: dict[str, str] = {
    label: key
    for key, translations in BUTTONS.items()
    for label in translations.values()
}

# ── Translations ──────────────────────────────────────────
T: dict[str, dict[str, str]] = {
    "welcome": {
        "ne": (
            "नमस्ते! 🙏 म *Bridge AI* हुँ।\n\n"
            "कोरियाबाट घर पैसा पठाउन सबैभन्दा राम्रो दर खोज्नुस् 💰\n\n"
            "IME Nepal, Wise, Hana Bank, Western Union — एकैपटक तुलना!"
        ),
        "vi": (
            "Xin chào! 🙏 Tôi là *Bridge AI*.\n\n"
            "Tìm tỷ giá tốt nhất để gửi tiền từ Hàn Quốc 💰\n\n"
            "So sánh Wise, Hana Bank, Western Union, Remitly và nhiều hơn!"
        ),
        "en": (
            "Hello! 🙏 I'm *Bridge AI*.\n\n"
            "Find the best rate to send money from Korea 💰\n\n"
            "Compare Wise, Hana Bank, Western Union, Remitly and more!"
        ),
        "tl": (
            "Kumusta! 🙏 Ako si *Bridge AI*.\n\n"
            "Hanapin ang pinakamahusay na rate para magpadala mula Korea 💰\n\n"
            "Ikukumpara ang Wise, Hana Bank, Western Union, Remitly at iba pa!"
        ),
        "id": (
            "Halo! 🙏 Saya *Bridge AI*.\n\n"
            "Temukan nilai tukar terbaik untuk mengirim uang dari Korea 💰\n\n"
            "Membandingkan Wise, Hana Bank, Western Union, Remitly dan lainnya!"
        ),
        "uz": (
            "Salom! 🙏 Men *Bridge AI* man.\n\n"
            "Koreadan pul yuborishning eng yaxshi kursini toping 💰\n\n"
            "Wise, Hana Bank, Western Union, Remitly va boshqalarni taqqoslayman!"
        ),
        "th": (
            "สวัสดี! 🙏 ผมคือ *Bridge AI*\n\n"
            "ค้นหาอัตราแลกเปลี่ยนที่ดีที่สุดสำหรับส่งเงินจากเกาหลี 💰\n\n"
            "เปรียบเทียบ Wise, Hana Bank, Western Union, Remitly และอื่นๆ!"
        ),
        "zh": (
            "你好！🙏 我是 *Bridge AI*。\n\n"
            "从韩国以最佳汇率汇款 💰\n\n"
            "比较 Wise、Hana Bank、Western Union、Remitly 等平台！"
        ),
    },
    "ask_amount": {
        "ne": "₩ कति पठाउन चाहनुहुन्छ? (KRW मा)\n\nउदाहरण: *500000*",
        "vi": "₩ Bạn muốn gửi bao nhiêu? (KRW)\n\nVí dụ: *500000*",
        "en": "₩ How much do you want to send? (in KRW)\n\nExample: *500000*",
        "tl": "₩ Magkano ang gusto mong ipadala? (KRW)\n\nHalimbawa: *500000*",
        "id": "₩ Berapa yang ingin Anda kirim? (dalam KRW)\n\nContoh: *500000*",
        "uz": "₩ Qancha pul yubormoqchisiz? (KRW da)\n\nMisol: *500000*",
        "th": "₩ คุณต้องการส่งเงินเท่าไหร่? (KRW)\n\nตัวอย่าง: *500000*",
        "zh": "₩ 您想汇多少钱？（以KRW计）\n\n示例：*500000*",
    },
    "comparing": {
        "ne": "⏳ दर खोज्दैछु...",
        "vi": "⏳ Đang tìm tỷ giá...",
        "en": "⏳ Fetching live rates...",
        "tl": "⏳ Kinukuha ang mga rate...",
        "id": "⏳ Mengambil kurs...",
        "uz": "⏳ Kurslar olinmoqda...",
        "th": "⏳ กำลังดึงอัตราแลกเปลี่ยน...",
        "zh": "⏳ 正在获取实时汇率...",
    },
    "send_button": {
        "ne": "यहाँ पठाउनुस् →",  "vi": "Gửi tại đây →",  "en": "Send Here →",
        "tl": "Magpadala Dito →",  "id": "Kirim Di Sini →", "uz": "Bu yerda →",
        "th": "ส่งที่นี่ →",        "zh": "在此汇款 →",
    },
    "invalid_amount": {
        "ne": "❌ सही रकम लेख्नुस् (उदाहरण: 500000)",
        "vi": "❌ Nhập số tiền hợp lệ (ví dụ: 500000)",
        "en": "❌ Please enter a valid amount (example: 500000)",
        "tl": "❌ Maglagay ng wastong halaga (halimbawa: 500000)",
        "id": "❌ Masukkan jumlah yang valid (contoh: 500000)",
        "uz": "❌ To'g'ri miqdorni kiriting (misol: 500000)",
        "th": "❌ กรอกจำนวนเงินที่ถูกต้อง (เช่น 500000)",
        "zh": "❌ 请输入有效金额（例如：500000）",
    },
    "amount_too_low": {
        "ne": "❌ न्यूनतम ₩10,000",   "vi": "❌ Tối thiểu ₩10,000",
        "en": "❌ Minimum ₩10,000",    "tl": "❌ Minimum ₩10,000",
        "id": "❌ Minimum ₩10,000",    "uz": "❌ Minimal ₩10,000",
        "th": "❌ ขั้นต่ำ ₩10,000",    "zh": "❌ 最低 ₩10,000",
    },
    "amount_too_high": {
        "ne": "❌ अधिकतम ₩5,000,000",  "vi": "❌ Tối đa ₩5,000,000",
        "en": "❌ Maximum ₩5,000,000",  "tl": "❌ Maximum ₩5,000,000",
        "id": "❌ Maksimum ₩5,000,000", "uz": "❌ Maksimal ₩5,000,000",
        "th": "❌ สูงสุด ₩5,000,000",  "zh": "❌ 最高 ₩5,000,000",
    },
    "rate_error": {
        "ne": "⚠️ दर लोड गर्न सकिएन। कृपया फेरि प्रयास गर्नुस्।",
        "vi": "⚠️ Không thể tải tỷ giá. Vui lòng thử lại.",
        "en": "⚠️ Could not load rates. Please try again.",
        "tl": "⚠️ Hindi ma-load ang mga rate. Subukan ulit.",
        "id": "⚠️ Tidak dapat memuat kurs. Coba lagi.",
        "uz": "⚠️ Kurslarni yuklab bo'lmadi. Qayta urinib ko'ring.",
        "th": "⚠️ ไม่สามารถโหลดอัตราได้ กรุณาลองใหม่",
        "zh": "⚠️ 无法加载汇率，请重试。",
    },
    "help": {
        "ne": (
            "📖 *Bridge Bot सहयोग*\n\n"
            "• /send — पैसा पठाउने दर खोज्नुस्\n"
            "• /rates — हालको दरहरू हेर्नुस्\n"
            "• /alert — दर अलर्ट सेट गर्नुस्\n"
            "• /myalerts — मेरो अलर्टहरू\n"
            "• /language — भाषा परिवर्तन\n"
            "• /help — यो सन्देश\n\n"
            "✅ Bridge ले तपाईंको पैसा कहिल्यै छुँदैन।"
        ),
        "vi": (
            "📖 *Bridge Bot Trợ giúp*\n\n"
            "• /send — Tìm tỷ giá tốt nhất\n"
            "• /rates — Xem tỷ giá hiện tại\n"
            "• /alert — Đặt cảnh báo tỷ giá\n"
            "• /myalerts — Xem cảnh báo của tôi\n"
            "• /language — Thay đổi ngôn ngữ\n"
            "• /help — Tin nhắn này\n\n"
            "✅ Bridge không bao giờ chạm vào tiền của bạn."
        ),
        "en": (
            "📖 *Bridge Bot Help*\n\n"
            "• /send — Find best rate to send money\n"
            "• /rates — See current rates\n"
            "• /alert — Set a rate alert\n"
            "• /myalerts — View your alerts\n"
            "• /language — Change language\n"
            "• /help — This message\n\n"
            "✅ Bridge never touches your money. We only compare."
        ),
        "tl": (
            "📖 *Bridge Bot Tulong*\n\n"
            "• /send — Hanapin ang pinakamahusay na rate\n"
            "• /rates — Tingnan ang kasalukuyang rates\n"
            "• /alert — Magtakda ng rate alert\n"
            "• /myalerts — Tingnan ang aking mga alert\n"
            "• /language — Baguhin ang wika\n"
            "• /help — Mensaheng ito\n\n"
            "✅ Hindi kailanman hahawakan ng Bridge ang iyong pera."
        ),
        "id": (
            "📖 *Bridge Bot Bantuan*\n\n"
            "• /send — Temukan nilai tukar terbaik\n"
            "• /rates — Lihat kurs saat ini\n"
            "• /alert — Atur peringatan kurs\n"
            "• /myalerts — Lihat peringatan saya\n"
            "• /language — Ubah bahasa\n"
            "• /help — Pesan ini\n\n"
            "✅ Bridge tidak pernah menyentuh uang Anda."
        ),
        "uz": (
            "📖 *Bridge Bot Yordam*\n\n"
            "• /send — Eng yaxshi kursni toping\n"
            "• /rates — Joriy kurslarni ko'ring\n"
            "• /alert — Kurs ogohlantirish o'rnating\n"
            "• /myalerts — Mening ogohlantirishlarim\n"
            "• /language — Tilni o'zgartirish\n"
            "• /help — Bu xabar\n\n"
            "✅ Bridge hech qachon pulingizga tegmaydi."
        ),
        "th": (
            "📖 *Bridge Bot ช่วยเหลือ*\n\n"
            "• /send — หาอัตราที่ดีที่สุด\n"
            "• /rates — ดูอัตราปัจจุบัน\n"
            "• /alert — ตั้งการแจ้งเตือนอัตรา\n"
            "• /myalerts — ดูการแจ้งเตือนของฉัน\n"
            "• /language — เปลี่ยนภาษา\n"
            "• /help — ข้อความนี้\n\n"
            "✅ Bridge ไม่เคยแตะต้องเงินของคุณ"
        ),
        "zh": (
            "📖 *Bridge Bot 帮助*\n\n"
            "• /send — 查找最佳汇率\n"
            "• /rates — 查看当前汇率\n"
            "• /alert — 设置汇率提醒\n"
            "• /myalerts — 查看我的提醒\n"
            "• /language — 更改语言\n"
            "• /help — 此消息\n\n"
            "✅ Bridge 从不接触您的钱，只做比较。"
        ),
    },
    "main_menu_prompt": {
        "ne": "के गर्न चाहनुहुन्छ?",         "vi": "Bạn muốn làm gì?",
        "en": "What would you like to do?",   "tl": "Ano ang gusto mong gawin?",
        "id": "Apa yang ingin Anda lakukan?", "uz": "Nima qilmoqchisiz?",
        "th": "คุณต้องการทำอะไร?",           "zh": "您想做什么？",
    },
    "alert_ask_rate": {
        "ne": (
            "🔔 *दर अलर्ट सेट गर्नुस्*\n\n"
            "हालको सबैभन्दा राम्रो दर: *1 KRW = {rate:.5f} {currency}*\n\n"
            "कुन दरमा सूचना पाउन चाहनुहुन्छ?\n"
            "उदाहरण: `{suggested}`\n\n"
            "_रद्द गर्न /cancel लेख्नुस्_"
        ),
        "vi": (
            "🔔 *Đặt cảnh báo tỷ giá*\n\n"
            "Tỷ giá tốt nhất hiện tại: *1 KRW = {rate:.5f} {currency}*\n\n"
            "Bạn muốn được thông báo ở tỷ giá nào?\n"
            "Ví dụ: `{suggested}`\n\n"
            "_Để hủy: /cancel_"
        ),
        "en": (
            "🔔 *Set Rate Alert*\n\n"
            "Current best rate: *1 KRW = {rate:.5f} {currency}*\n\n"
            "What rate do you want to be notified at?\n"
            "Example: `{suggested}`\n\n"
            "_Type /cancel to cancel_"
        ),
        "tl": (
            "🔔 *Magtakda ng Rate Alert*\n\n"
            "Pinakamahusay na rate ngayon: *1 KRW = {rate:.5f} {currency}*\n\n"
            "Sa anong rate ka gusto ng abiso?\n"
            "Halimbawa: `{suggested}`\n\n"
            "_I-type ang /cancel para kanselahin_"
        ),
        "id": (
            "🔔 *Atur Peringatan Kurs*\n\n"
            "Kurs terbaik saat ini: *1 KRW = {rate:.5f} {currency}*\n\n"
            "Di kurs berapa Anda ingin diberitahu?\n"
            "Contoh: `{suggested}`\n\n"
            "_Ketik /cancel untuk membatalkan_"
        ),
        "uz": (
            "🔔 *Kurs ogohlantirish o'rnating*\n\n"
            "Hozirgi eng yaxshi kurs: *1 KRW = {rate:.5f} {currency}*\n\n"
            "Qaysi kursda xabar olishni xohlaysiz?\n"
            "Misol: `{suggested}`\n\n"
            "_Bekor qilish uchun /cancel yozing_"
        ),
        "th": (
            "🔔 *ตั้งการแจ้งเตือนอัตรา*\n\n"
            "อัตราที่ดีที่สุดตอนนี้: *1 KRW = {rate:.5f} {currency}*\n\n"
            "คุณต้องการแจ้งเตือนที่อัตราเท่าไหร่?\n"
            "ตัวอย่าง: `{suggested}`\n\n"
            "_พิมพ์ /cancel เพื่อยกเลิก_"
        ),
        "zh": (
            "🔔 *设置汇率提醒*\n\n"
            "当前最佳汇率: *1 KRW = {rate:.5f} {currency}*\n\n"
            "您希望在什么汇率时收到通知？\n"
            "示例: `{suggested}`\n\n"
            "_输入 /cancel 取消_"
        ),
    },
    "alert_confirm": {
        "ne": "✅ अलर्ट सेट!\n\n1 KRW = *{rate}* {currency} पुग्दा म तपाईंलाई सूचित गर्नेछु। 🔔",
        "vi": "✅ Đã đặt cảnh báo!\n\nTôi sẽ thông báo khi 1 KRW = *{rate}* {currency}. 🔔",
        "en": "✅ Alert set!\n\nI'll notify you when 1 KRW = *{rate}* {currency}. 🔔",
        "tl": "✅ Naitakda na ang alert!\n\nAabisuhan kita kapag 1 KRW = *{rate}* {currency}. 🔔",
        "id": "✅ Peringatan diatur!\n\nSaya akan memberi tahu Anda ketika 1 KRW = *{rate}* {currency}. 🔔",
        "uz": "✅ Ogohlantirish o'rnatildi!\n\n1 KRW = *{rate}* {currency} bo'lganda xabar beraman. 🔔",
        "th": "✅ ตั้งการแจ้งเตือนแล้ว!\n\nฉันจะแจ้งเตือนคุณเมื่อ 1 KRW = *{rate}* {currency} 🔔",
        "zh": "✅ 提醒已设置！\n\n当 1 KRW = *{rate}* {currency} 时我会通知您。🔔",
    },
    "alert_triggered": {
        "ne": (
            "🔔 *दर अलर्ट!*\n\n"
            "तपाईंको लक्ष्य दर पूरा भयो!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "अहिले पठाउनुस् 👉 /send"
        ),
        "vi": (
            "🔔 *Cảnh báo tỷ giá!*\n\n"
            "Tỷ giá mục tiêu của bạn đã đạt!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "Gửi ngay 👉 /send"
        ),
        "en": (
            "🔔 *Rate Alert!*\n\n"
            "Your target rate has been reached!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "Send now 👉 /send"
        ),
        "tl": (
            "🔔 *Rate Alert!*\n\n"
            "Naabot na ang iyong target na rate!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "Magpadala na 👉 /send"
        ),
        "id": (
            "🔔 *Peringatan Kurs!*\n\n"
            "Kurs target Anda telah tercapai!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "Kirim sekarang 👉 /send"
        ),
        "uz": (
            "🔔 *Kurs ogohlantirgichi!*\n\n"
            "Maqsadli kurs bajarildi!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "Hozir yuboring 👉 /send"
        ),
        "th": (
            "🔔 *แจ้งเตือนอัตราแลกเปลี่ยน!*\n\n"
            "อัตราเป้าหมายของคุณถึงแล้ว!\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "ส่งเงินเดี๋ยวนี้ 👉 /send"
        ),
        "zh": (
            "🔔 *汇率提醒!*\n\n"
            "您的目标汇率已达到！\n"
            "*1 KRW = {rate:.5f} {currency}*\n\n"
            "立即汇款 👉 /send"
        ),
    },
    "alert_invalid_rate": {
        "ne": "❌ कृपया सही दर लेख्नुस् (उदाहरण: 0.108)\n\nरद्द गर्न /cancel",
        "vi": "❌ Nhập tỷ giá hợp lệ (ví dụ: 0.108)\n\nHủy: /cancel",
        "en": "❌ Enter a valid rate (example: 0.108)\n\nCancel: /cancel",
        "tl": "❌ Mag-input ng wastong rate (halimbawa: 0.108)\n\nKanselahin: /cancel",
        "id": "❌ Masukkan kurs yang valid (contoh: 0.108)\n\nBatalkan: /cancel",
        "uz": "❌ To'g'ri kurs kiriting (misol: 0.108)\n\nBekor qilish: /cancel",
        "th": "❌ กรอกอัตราที่ถูกต้อง (เช่น 0.108)\n\nยกเลิก: /cancel",
        "zh": "❌ 请输入有效汇率（例如：0.108）\n\n取消：/cancel",
    },
    "no_alerts": {
        "ne": "📭 तपाईंको कुनै सक्रिय अलर्ट छैन।\n\n/alert लेखेर नयाँ अलर्ट सेट गर्नुस्।",
        "vi": "📭 Bạn không có cảnh báo nào.\n\nDùng /alert để đặt cảnh báo mới.",
        "en": "📭 You have no active alerts.\n\nUse /alert to set one.",
        "tl": "📭 Wala kang aktibong mga alert.\n\nGamitin ang /alert para magtakda ng isa.",
        "id": "📭 Anda tidak memiliki peringatan aktif.\n\nGunakan /alert untuk mengatur.",
        "uz": "📭 Sizda faol ogohlantirishlar yo'q.\n\nYangi o'rnatish uchun /alert yozing.",
        "th": "📭 คุณไม่มีการแจ้งเตือนที่ใช้งานอยู่\n\nใช้ /alert เพื่อตั้งค่า",
        "zh": "📭 您没有活跃的提醒。\n\n使用 /alert 设置新提醒。",
    },
    "cancelled": {
        "ne": "❌ रद्द गरियो।",   "vi": "❌ Đã hủy.",
        "en": "❌ Cancelled.",      "tl": "❌ Nakansela.",
        "id": "❌ Dibatalkan.",    "uz": "❌ Bekor qilindi.",
        "th": "❌ ยกเลิกแล้ว",    "zh": "❌ 已取消。",
    },
    "language_changed": {
        "ne": "✅ भाषा परिवर्तन भयो।", "vi": "✅ Đã thay đổi ngôn ngữ.",
        "en": "✅ Language changed.",   "tl": "✅ Nabago ang wika.",
        "id": "✅ Bahasa diubah.",      "uz": "✅ Til o'zgartirildi.",
        "th": "✅ เปลี่ยนภาษาแล้ว",   "zh": "✅ 语言已更改。",
    },
}


# ── Translation helpers ───────────────────────────────────

def t(key: str, lang: str) -> str:
    """Return translation for key in lang, falling back to English."""
    return T.get(key, {}).get(lang) or T.get(key, {}).get("en", key)


def btn(key: str, lang: str) -> str:
    """Return localised button label."""
    return BUTTONS.get(key, {}).get(lang) or BUTTONS.get(key, {}).get("en", key)


def get_user_lang(context: ContextTypes.DEFAULT_TYPE, update: Update = None) -> str:
    """
    Resolve user language: stored preference → Telegram locale → English.
    """
    lang = context.user_data.get("language")
    if lang:
        return lang
    if update and update.effective_user:
        tg = (update.effective_user.language_code or "").lower()
        for prefix, code in _TG_LANG_MAP.items():
            if tg.startswith(prefix):
                return code
    return "en"


def get_user_currency(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("currency", "NPR")


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(btn("send_money", lang))],
            [KeyboardButton(btn("rates", lang)), KeyboardButton(btn("alert", lang))],
            [KeyboardButton(btn("help", lang))],
        ],
        resize_keyboard=True,
    )


# ── Command handlers ──────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — show language selection or welcome back."""
    user = update.effective_user
    logger.info(f"Start | user={user.id} | @{user.username} | {user.full_name}")

    existing = get_user(user.id)
    if existing:
        lang = existing.get("language", "en")
        context.user_data["language"] = lang
        context.user_data["currency"] = existing.get("currency", "NPR")
        await update.message.reply_text(
            t("welcome", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="Markdown",
        )
        return MAIN_MENU

    # New user — ask language first
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"lang_{code}")]
        for code, label in LANGUAGES.items()
    ]
    await update.message.reply_text(
        "🌐 Choose your language / 언어를 선택하세요:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_LANGUAGE


async def language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle initial language selection callback."""
    query = update.callback_query
    await query.answer()

    lang = query.data.replace("lang_", "")
    currency = CURRENCIES.get(lang, "USD")
    context.user_data["language"] = lang
    context.user_data["currency"] = currency

    user = update.effective_user
    save_user(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        language=lang,
        currency=currency,
    )

    await query.edit_message_text(
        t("welcome", lang), parse_mode="Markdown"
    )
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=t("ask_amount", lang),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="Markdown",
    )
    return MAIN_MENU


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /language — show language picker."""
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"changelang_{code}")]
        for code, label in LANGUAGES.items()
    ]
    await update.message.reply_text(
        "🌐 Choose language / 언어 선택:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_LANGUAGE


async def change_language_chosen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle language change callback."""
    query = update.callback_query
    await query.answer()

    lang = query.data.replace("changelang_", "")
    currency = CURRENCIES.get(lang, "USD")
    context.user_data["language"] = lang
    context.user_data["currency"] = currency

    update_user(update.effective_user.id, {"language": lang, "currency": currency})

    await query.edit_message_text(t("language_changed", lang))
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=t("main_menu_prompt", lang),
        reply_markup=main_menu_keyboard(lang),
    )
    return MAIN_MENU


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /send — ask for amount."""
    lang = get_user_lang(context, update)
    await update.message.reply_text(
        t("ask_amount", lang), parse_mode="Markdown"
    )
    return ENTERING_AMOUNT


async def cmd_rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /rates — show current rates without amount."""
    lang     = get_user_lang(context, update)
    currency = get_user_currency(context)

    loading = await update.message.reply_text(t("comparing", lang))
    rates   = await get_live_rates("KRW", currency)
    text    = format_comparison(rates, 0, currency, lang, show_amounts=False)
    await loading.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    return MAIN_MENU


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /help."""
    lang = get_user_lang(context, update)
    await update.message.reply_text(
        t("help", lang),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(lang),
    )
    return MAIN_MENU


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel — exits any multi-step flow back to main menu."""
    lang = get_user_lang(context, update)
    context.user_data.pop("alert_currency", None)
    await update.message.reply_text(
        t("cancelled", lang), reply_markup=main_menu_keyboard(lang)
    )
    return MAIN_MENU


async def cmd_set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /alert — show current rate and ask for target."""
    lang     = get_user_lang(context, update)
    currency = get_user_currency(context)
    context.user_data["alert_currency"] = currency

    rates = await get_live_rates("KRW", currency)
    if not rates:
        await update.message.reply_text(t("rate_error", lang))
        return MAIN_MENU

    best_rate = max(rates, key=lambda x: x["rate"])["rate"]
    suggested = round(best_rate * 1.02, 5)   # 2% above current

    msg = t("alert_ask_rate", lang).format(
        rate=best_rate, currency=currency, suggested=suggested
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ENTERING_ALERT_RATE


async def handle_alert_rate_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive and store the target rate from the user."""
    lang     = get_user_lang(context, update)
    currency = context.user_data.get("alert_currency", get_user_currency(context))
    text     = update.message.text.strip()

    # Allow menu buttons to redirect even while in this state
    action = _BTN_REVERSE.get(text)
    if action:
        context.user_data.pop("alert_currency", None)
        return await _dispatch_button(action, update, context)

    try:
        target = float(text.replace(",", "").replace(" ", ""))
        if target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("alert_invalid_rate", lang))
        return ENTERING_ALERT_RATE

    save_alert(
        user_id=update.effective_user.id,
        currency=currency,
        target_rate=target,
        lang=lang,
    )
    context.user_data.pop("alert_currency", None)

    await update.message.reply_text(
        t("alert_confirm", lang).format(rate=target, currency=currency),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(lang),
    )
    return MAIN_MENU


async def cmd_my_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /myalerts — list user's active alerts."""
    lang    = get_user_lang(context, update)
    alerts  = get_user_alerts(update.effective_user.id)

    if not alerts:
        await update.message.reply_text(t("no_alerts", lang))
        return MAIN_MENU

    currency_names = {
        "NPR": "🇳🇵 NPR", "VND": "🇻🇳 VND", "PHP": "🇵🇭 PHP",
        "IDR": "🇮🇩 IDR", "UZS": "🇺🇿 UZS", "THB": "🇹🇭 THB",
        "BDT": "🇧🇩 BDT", "USD": "🇺🇸 USD", "CNY": "🇨🇳 CNY",
    }

    lines = ["🔔 *Active Alerts:*\n"]
    for a in alerts:
        cur  = a["currency"]
        flag = currency_names.get(cur, cur)
        lines.append(f"• {flag} → 1 KRW = *{a['target_rate']}*")

    lines.append(
        "\n_To cancel an alert, set a new one on the same currency "
        "or it auto-removes when triggered._"
    )
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown"
    )
    return MAIN_MENU


async def cmd_clickstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /clickstats — Revenue-focused click summary for bot owner.
    Shows intent clicks from referral_clicks.json +
    links to the real-click tracker dashboard.
    """
    admin_id = os.getenv("ADMIN_USER_ID", "")
    if str(update.effective_user.id) != str(admin_id):
        return MAIN_MENU

    data         = get_referral_stats()
    tracking_url = os.getenv("TRACKING_BASE_URL", "")
    stats_secret = os.getenv("STATS_SECRET", "")

    lines = ["📈 *Click & Revenue Log*\n"]

    # Intent clicks breakdown
    lines.append(f"*Intent clicks* (comparison views): `{data['total_clicks']}`")
    if data["by_platform"]:
        lines.append("\nBy platform:")
        for platform, count in sorted(
            data["by_platform"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"  • {platform}: {count}")

    # Last 7 days
    recent = list(sorted(data["by_date"].items(), reverse=True))[:7]
    if recent:
        lines.append("\nLast 7 days:")
        for date, count in recent:
            lines.append(f"  • {date}: {count} comparisons")

    # Real click tracker link
    if tracking_url:
        secret_param = f"?secret={stats_secret}" if stats_secret else ""
        lines.append(
            f"\n🔗 *Real click dashboard:*\n"
            f"[{tracking_url}/stats{secret_param}]"
            f"({tracking_url}/stats{secret_param})"
        )
    else:
        lines.append(
            "\n⚠️ Set `TRACKING_BASE_URL` in your env to enable "
            "real click tracking (tracker.py)."
        )

    # Affiliate sign-up reminder
    lines.append(
        "\n💡 *Affiliate programs to sign up:*\n"
        "• [Wise Partners](https://wise.com/partners) — $10-25/user\n"
        "• [Remitly Affiliate](https://remitly.com/affiliate) — $10-25/user"
    )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    return MAIN_MENU


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /admin — stats for bot owner only."""
    admin_id = os.getenv("ADMIN_USER_ID", "")
    if str(update.effective_user.id) != str(admin_id):
        return MAIN_MENU   # silently ignore

    user_stats    = get_stats()
    intent_clicks = get_referral_stats()   # logged when comparison shown
    alerts        = get_all_alerts()
    tracking_url  = os.getenv("TRACKING_BASE_URL", "")

    tracking_note = (
        f"\n🔗 Real-click tracker: [dashboard]({tracking_url}/stats)"
        if tracking_url else
        "\n⚠️ TRACKING_BASE_URL not set — only intent clicks logged"
    )

    msg = (
        f"📊 *Bridge Bot — Admin Dashboard*\n\n"
        f"👥 *Users:* {user_stats['total_users']}\n"
        f"🌐 By language: `{user_stats['by_language']}`\n"
        f"💱 By currency: `{user_stats['by_currency']}`\n\n"
        f"📌 *Intent clicks* (shown = possible click): {intent_clicks['total_clicks']}\n"
        f"Top platforms: `{dict(list(intent_clicks['by_platform'].items())[:4])}`\n"
        f"{tracking_note}\n\n"
        f"🔔 Active rate alerts: {len(alerts)}\n"
    )
    await update.message.reply_text(
        msg, parse_mode="Markdown", disable_web_page_preview=True
    )
    return MAIN_MENU


# ── Amount entry & comparison ─────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Central message handler for MAIN_MENU and ENTERING_AMOUNT states.

    Routing priority:
    1. Menu button press → dispatch to the relevant command
    2. Numeric input     → rate comparison
    3. Free text         → Claude AI response
    """
    lang = get_user_lang(context, update)
    text = update.message.text.strip()

    # 1. Menu button?
    action = _BTN_REVERSE.get(text)
    if action:
        return await _dispatch_button(action, update, context)

    # 2. Looks like an amount?
    amount_str = text.replace(",", "").replace("₩", "").replace("\\", "").replace(" ", "")
    try:
        amount = int(float(amount_str))
        return await _do_comparison(update, context, amount, lang)
    except ValueError:
        pass

    # 3. Free-text → AI
    await _ai_reply(update, context, text, lang)
    return MAIN_MENU


async def _dispatch_button(
    action: str, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if action == "send_money":
        return await cmd_send(update, context)
    if action == "rates":
        return await cmd_rates(update, context)
    if action == "alert":
        return await cmd_set_alert(update, context)
    if action == "help":
        return await cmd_help(update, context)
    return MAIN_MENU


async def _do_comparison(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    amount: int,
    lang: str,
) -> int:
    """Validate amount, fetch rates, display comparison with referral buttons."""
    currency = get_user_currency(context)

    if amount < 10_000:
        await update.message.reply_text(t("amount_too_low", lang))
        return ENTERING_AMOUNT
    if amount > 5_000_000:
        await update.message.reply_text(t("amount_too_high", lang))
        return ENTERING_AMOUNT

    loading = await update.message.reply_text(t("comparing", lang))

    try:
        rates = await get_live_rates("KRW", currency)
        text  = format_comparison(rates, amount, currency, lang)

        # Referral buttons for top 3 platforms
        sorted_rates = sorted(rates, key=lambda x: x["rate"] * (
            amount - x["fee_flat_krw"] - amount * x["fee_percent"]
        ), reverse=True)[:3]

        buttons = []
        for r in sorted_rates:
            # Use callback button so the bot gets notified on tap → real click log
            buttons.append([
                InlineKeyboardButton(
                    f"{t('send_button', lang)} {r['platform']}",
                    callback_data=f"go|{r['platform']}|{amount}|{currency}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🔔 " + ("Alert" if lang == "en" else t("alert_ask_rate", lang)[:8]),
                callback_data=f"alert_{amount}_{currency}",
            ),
            InlineKeyboardButton(
                "🔄 " + ("Again" if lang == "en" else "Again"),
                callback_data="send_again",
            ),
        ])

        await loading.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True,
        )

        increment_comparison(update.effective_user.id)
        logger.info(
            f"Comparison | user={update.effective_user.id} | "
            f"amount={amount} KRW | currency={currency} | lang={lang}"
        )

    except Exception as e:
        logger.error(f"Comparison error: {e}")
        await loading.edit_text(t("rate_error", lang))

    return MAIN_MENU


async def _ai_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    lang: str,
) -> None:
    """Send a Claude AI response for free-text messages."""
    typing_msg = await update.message.reply_text("💭 ...")
    try:
        reply = await get_ai_response(text, lang)
        await typing_msg.edit_text(reply)
    except Exception as e:
        logger.error(f"AI reply error: {e}")
        await typing_msg.delete()


# ── Inline button callbacks ───────────────────────────────

async def handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()

    # ── "Send Here" button tap → real click log ──────────
    if query.data.startswith("go|"):
        parts    = query.data.split("|")
        platform = parts[1]
        amount   = int(parts[2])
        currency = parts[3]
        lang     = get_user_lang(context, update)
        user     = update.effective_user

        # Log the actual click (user intentionally tapped the button)
        log_click(
            user_id=user.id,
            platform=platform,
            amount=amount,
            currency=currency,
            click_type="actual",
        )
        log_user_click(
            user_id=user.id,
            platform=platform,
            amount=amount,
            currency=currency,
        )
        logger.info(
            f"ACTUAL CLICK | user={user.id} | @{user.username} | "
            f"platform={platform} | amount={amount} KRW | currency={currency}"
        )

        ref_url = generate_referral_link(
            platform=platform,
            user_id=user.id,
            amount=amount,
            currency=currency,
        )
        send_label = {
            "ne": f"➡️ {platform} मा जानुस्",
            "vi": f"➡️ Đến {platform}",
            "en": f"➡️ Go to {platform}",
            "tl": f"➡️ Pumunta sa {platform}",
            "id": f"➡️ Pergi ke {platform}",
            "uz": f"➡️ {platform} ga o'ting",
            "th": f"➡️ ไปที่ {platform}",
            "zh": f"➡️ 前往 {platform}",
        }
        await query.answer()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=send_label.get(lang, send_label["en"]),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"🔗 Open {platform}", url=ref_url)
            ]]),
        )
        return MAIN_MENU

    if query.data == "send_again":
        lang = get_user_lang(context, update)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=t("ask_amount", lang),
            parse_mode="Markdown",
        )
        return ENTERING_AMOUNT

    if query.data.startswith("alert_"):
        # e.g. alert_500000_NPR
        parts    = query.data.split("_")
        currency = parts[2] if len(parts) >= 3 else get_user_currency(context)
        lang     = get_user_lang(context, update)
        context.user_data["alert_currency"] = currency

        rates = await get_live_rates("KRW", currency)
        if not rates:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t("rate_error", lang),
            )
            return MAIN_MENU

        best_rate = max(rates, key=lambda x: x["rate"])["rate"]
        suggested = round(best_rate * 1.02, 5)
        msg = t("alert_ask_rate", lang).format(
            rate=best_rate, currency=currency, suggested=suggested
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=msg,
            parse_mode="Markdown",
        )
        return ENTERING_ALERT_RATE

    return MAIN_MENU


# ── Background job: rate alert checker ───────────────────

async def check_rate_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Runs every 30 minutes.
    Checks all pending rate alerts; sends notification if target is reached.
    """
    alerts = get_all_alerts()
    if not alerts:
        return

    logger.info(f"Checking {len(alerts)} rate alerts...")

    # Group by currency to fetch each rate only once
    by_currency: dict[str, list] = {}
    for a in alerts:
        by_currency.setdefault(a["currency"], []).append(a)

    for currency, currency_alerts in by_currency.items():
        try:
            rates = await get_live_rates("KRW", currency)
            if not rates:
                continue
            best_rate = max(rates, key=lambda x: x["rate"])["rate"]
        except Exception as e:
            logger.error(f"Alert check rate error for {currency}: {e}")
            continue

        for alert in currency_alerts:
            if best_rate >= alert["target_rate"]:
                lang = alert.get("lang", "en")
                msg  = t("alert_triggered", lang).format(
                    rate=best_rate, currency=currency
                )
                try:
                    await context.bot.send_message(
                        chat_id=alert["user_id"],
                        text=msg,
                        parse_mode="Markdown",
                    )
                    remove_alert(alert["user_id"], currency)
                    logger.info(
                        f"Alert triggered | user={alert['user_id']} | "
                        f"rate={best_rate:.5f} | target={alert['target_rate']} | "
                        f"currency={currency}"
                    )
                except Exception as e:
                    logger.error(f"Could not send alert to {alert['user_id']}: {e}")


# ── Error handler ─────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update caused error: {context.error}", exc_info=context.error)


# ── Main ──────────────────────────────────────────────────

def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()

    # All command fallbacks (work in any conversation state)
    all_fallbacks = [
        CommandHandler("start",      start),
        CommandHandler("help",       cmd_help),
        CommandHandler("send",       cmd_send),
        CommandHandler("rates",      cmd_rates),
        CommandHandler("language",   cmd_language),
        CommandHandler("alert",      cmd_set_alert),
        CommandHandler("myalerts",   cmd_my_alerts),
        CommandHandler("cancel",     cmd_cancel),
        CommandHandler("admin",      cmd_admin),
        CommandHandler("clickstats", cmd_clickstats),
    ]

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        ],
        states={
            CHOOSING_LANGUAGE: [
                CallbackQueryHandler(language_chosen,        pattern=r"^lang_"),
                CallbackQueryHandler(change_language_chosen, pattern=r"^changelang_"),
            ],
            ENTERING_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            ENTERING_ALERT_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_alert_rate_input),
            ],
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
                CallbackQueryHandler(handle_callback),
            ],
        },
        fallbacks=all_fallbacks,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_error_handler(error_handler)

    # Background job: check rate alerts every 30 minutes, first check after 60s
    if app.job_queue:
        app.job_queue.run_repeating(
            check_rate_alerts,
            interval=1800,
            first=60,
            name="rate_alert_checker",
        )
        logger.info("Rate alert checker job registered (every 30 min)")
    else:
        logger.warning(
            "JobQueue not available — rate alerts won't be checked automatically. "
            "Install with: pip install 'python-telegram-bot[job-queue]'"
        )

    logger.info("🚀 Bridge Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
