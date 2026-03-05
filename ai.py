"""
ai.py — Static response handler (no AI API)
============================================
Returns helpful static messages directing users to bot commands.
"""

import logging

logger = logging.getLogger(__name__)


async def get_ai_response(_user_message: str, user_lang: str = "en") -> str:
    return _fallback_response(user_lang)


async def get_savings_insight(
    _spending_data: dict,
    _user_lang: str = "en",
    _nationality: str = "foreign worker",
) -> str:
    return ""


def _fallback_response(lang: str) -> str:
    responses = {
        "ne": "💸 /send लेखेर सबैभन्दा राम्रो दर हेर्नुस्!",
        "en": "💸 Type /send to find the best rate to send money home!",
        "vi": "💸 Nhập /send để tìm tỷ giá tốt nhất!",
        "tl": "💸 I-type ang /send para makita ang pinakamahusay na rate!",
        "id": "💸 Ketik /send untuk menemukan nilai tukar terbaik!",
        "uz": "💸 /send yozing va eng yaxshi kursni toping!",
        "th": "💸 พิมพ์ /send เพื่อค้นหาอัตราแลกเปลี่ยนที่ดีที่สุด!",
        "zh": "💸 输入 /send 查找最佳汇率！",
    }
    return responses.get(lang, responses["en"])
