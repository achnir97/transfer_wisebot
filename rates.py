"""
rates.py — Live exchange rate aggregator
=========================================
GME and Hanpass: real rates fetched directly from their APIs via fetchers.py
All data is live — no static estimates or fallbacks.
"""

import asyncio
import json
import logging
import os
import time

from fetchers import RateFetcher

logger = logging.getLogger(__name__)


# ─── Platform configs ─────────────────────────────────────
# Only platforms with real live API endpoints

PLATFORMS = {
    "GME": {
        "color":          "🟤",
        "speed":          "1-2일 / 1-2 days",
        "url":            "https://online.gmeremit.com",
        "affiliate_base": "https://online.gmeremit.com/?utm_source=bridge_bot",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY", "KHR"],
    },
    "Hanpass": {
        "color":          "🔵",
        "speed":          "당일 / Same day",
        "url":            "https://www.hanpass.com",
        "affiliate_base": "https://www.hanpass.com/?utm_source=bridge_bot",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY", "KHR"],
    },
    "CrossEnf": {
        "color":          "🟢",
        "speed":          "당일 / Same day",
        "url":            "https://crossenf.com",
        "affiliate_base": "https://crossenf.com/?utm_source=bridge_bot",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY", "MNT", "KHR", "MMK", "LKR", "PKR"],
    },
    "E9Pay": {
        "color":          "🟠",
        "speed":          "당일 / Same day",
        "url":            "https://www.e9pay.co.kr",
        "affiliate_base": "https://www.e9pay.co.kr/?utm_source=bridge_bot",
        "currencies":     ["NPR"],   # E9Pay only supports NPR from Korea
    },
}

# ─── Rate cache ───────────────────────────────────────────
_rate_cache: dict = {}
CACHE_FILE         = "rate_cache.json"
CACHE_TTL_SECONDS  = 1800  # 30 minutes


def _load_cache() -> None:
    global _rate_cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, encoding="utf-8") as f:
                _rate_cache = json.load(f)
            logger.info(f"Loaded rate cache ({len(_rate_cache)} entries)")
    except Exception as e:
        logger.warning(f"Could not load cache: {e}")
        _rate_cache = {}


def _save_cache() -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_rate_cache, f)
    except Exception as e:
        logger.warning(f"Could not save cache: {e}")


def _cache_key(from_c: str, to_c: str) -> str:
    return f"{from_c}_{to_c}"


def _is_cache_fresh(key: str) -> bool:
    if key not in _rate_cache:
        return False
    age = time.time() - _rate_cache[key].get("fetched_at", 0)
    return age < CACHE_TTL_SECONDS


_load_cache()




# ─── Platform filter ──────────────────────────────────────

def get_platforms_for_currency(to_currency: str) -> list[str]:
    """Return platform names that support the destination currency."""
    return [
        name for name, cfg in PLATFORMS.items()
        if to_currency in cfg["currencies"]
    ]


# ─── Main public function ─────────────────────────────────

async def get_live_rates(from_currency: str, to_currency: str) -> list[dict]:
    """
    Fetch live rates from GME and Hanpass in parallel.
    Only real API data — no estimates or static fallbacks.
    Returns list sorted best → worst by rate.
    """
    cache_key = _cache_key(from_currency, to_currency)

    if _is_cache_fresh(cache_key):
        logger.info(f"Cache hit: {cache_key}")
        return _rate_cache[cache_key]["rates"]

    try:
        fetcher   = RateFetcher()
        real_data = await fetcher.fetch_all(from_currency, to_currency, send_amount=500_000)
        await fetcher.close()

        supported = get_platforms_for_currency(to_currency)
        rates: list[dict] = []

        for platform in supported:
            cfg   = PLATFORMS[platform]
            slug  = platform.lower()   # "gme" | "hanpass" | "crossenf"
            pdata = real_data.get(slug, {})

            if "error" in pdata or not pdata.get("exchange_rate"):
                lvl = logger.debug if "Unsupported currency" in str(pdata.get("error","")) else logger.warning
                lvl(f"{platform} skipped for {to_currency}: {pdata.get('error')}")
                continue

            rates.append({
                "platform":         platform,
                "rate":             round(float(pdata["exchange_rate"]), 6),
                "fee_flat_krw":     int(pdata.get("transfer_fee_krw") or 0),
                "fee_percent":      0.0,
                "speed":            pdata.get("transfer_speed", cfg["speed"]),
                "color":            cfg["color"],
                "url":              cfg["url"],
                "affiliate_base":   cfg["affiliate_base"],
                "recipient_amount": 0,
                "from_currency":    from_currency,
                "to_currency":      to_currency,
                "data_source":      "live",
            })

        _rate_cache[cache_key] = {"rates": rates, "fetched_at": time.time()}
        _save_cache()
        return rates

    except Exception as e:
        logger.error(f"Rate fetch failed for {from_currency}/{to_currency}: {e}")
        if cache_key in _rate_cache:
            logger.warning("Returning stale cached rates")
            return _rate_cache[cache_key]["rates"]
        return []


# ─── Formatting ───────────────────────────────────────────

def _fmt(n: float, decimals: int = 2) -> str:
    if decimals == 0:
        return f"{int(n):,}"
    return f"{n:,.{decimals}f}"


def _speed_short(speed: str) -> str:
    """Extract concise English speed label."""
    if "/" in speed:
        return speed.split("/")[-1].strip()
    return speed


_RANK_BADGE = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

_HEADER_AMOUNT = "💸 *₩{amount} → {currency}*"
_HEADER_RATES  = "📊 *{currency} — Live Rates*"
_DIVIDER       = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

_SAVINGS = {
    "ne": "💡 तुलना गरेर *{saving} {currency}* बचत गर्नुस्!",
    "vi": "💡 So sánh để tiết kiệm *{saving} {currency}*!",
    "en": "💡 Save up to *{saving} {currency}* by comparing!",
    "tl": "💡 Makatipid ng *{saving} {currency}* sa paghahambing!",
    "id": "💡 Hemat *{saving} {currency}* dengan membandingkan!",
    "uz": "💡 Taqqoslash orqali *{saving} {currency}* tejang!",
    "th": "💡 ประหยัด *{saving} {currency}* โดยการเปรียบเทียบ!",
    "zh": "💡 通过比较节省 *{saving} {currency}*！",
}

_DISCLAIMER = {
    "ne": "_Bridge ले तपाईंको पैसा छुँदैन — केवल तुलना गर्छ_",
    "vi": "_Bridge không bao giờ chạm vào tiền của bạn_",
    "en": "_Bridge never touches your money — comparison only_",
    "tl": "_Hindi hahawakan ng Bridge ang iyong pera_",
    "id": "_Bridge tidak pernah menyentuh uang Anda_",
    "uz": "_Bridge hech qachon pulingizga tegmaydi_",
    "th": "_Bridge ไม่เคยแตะต้องเงินของคุณ_",
    "zh": "_Bridge 从不接触您的钱_",
}


def format_comparison(
    rates: list[dict],
    amount_krw: int,
    to_currency: str,
    lang: str,
    show_amounts: bool = True,
) -> str:
    """
    Format rate comparison as Telegram Markdown.
    show_amounts=False → rate-only view (/rates command).
    """
    if not rates:
        no_rates = {
            "ne": "⚠️ दर लोड गर्न सकिएन। कृपया केही बेर पछि प्रयास गर्नुस्।",
            "en": "⚠️ Could not load rates. Please try again shortly.",
            "vi": "⚠️ Không thể tải tỷ giá. Vui lòng thử lại sau.",
        }
        return no_rates.get(lang, no_rates["en"])

    # Calculate recipient amounts
    for r in rates:
        if show_amounts and amount_krw > 0:
            fee_krw               = r["fee_flat_krw"] + (amount_krw * r["fee_percent"])
            net_krw               = amount_krw - fee_krw
            r["recipient_amount"] = net_krw * r["rate"]
            r["fee_total_krw"]    = fee_krw
        else:
            r["recipient_amount"] = r["rate"]

    sorted_rates = sorted(rates, key=lambda x: x["recipient_amount"], reverse=True)
    best  = sorted_rates[0]
    worst = sorted_rates[-1]

    # ── Header ────────────────────────────────────────────
    if show_amounts and amount_krw > 0:
        header = _HEADER_AMOUNT.format(amount=_fmt(amount_krw, 0), currency=to_currency)
    else:
        header = _HEADER_RATES.format(currency=to_currency)

    lines = [header, _DIVIDER, ""]

    # Pre-compute 1M KRW reference for every platform
    REF_AMOUNT = 1_000_000
    for r in rates:
        fee_1m              = r["fee_flat_krw"] + REF_AMOUNT * r["fee_percent"]
        net_1m              = REF_AMOUNT - fee_1m
        r["ref_1m_amount"]  = net_1m * r["rate"]

    # ── Platform rows ─────────────────────────────────────
    for i, r in enumerate(sorted_rates):
        badge    = _RANK_BADGE[i] if i < len(_RANK_BADGE) else "▪️"
        is_live  = r.get("data_source") == "live"
        live_tag = " `live`" if is_live else ""
        speed    = _speed_short(r["speed"])
        ref_1m   = _fmt(r["ref_1m_amount"], 2)

        if show_amounts and amount_krw > 0:
            recv     = _fmt(r["recipient_amount"], 2)
            fee      = _fmt(r["fee_total_krw"], 0)
            best_tag = "  ← _best_" if i == 0 else ""
            lines.append(
                f"{badge} {r['color']} *{r['platform']}*{live_tag}{best_tag}\n"
                f"   *{to_currency} {recv}*  ·  fee ₩{fee}  ·  {speed}\n"
                f"   _₩1,000,000 → {to_currency} {ref_1m}_"
            )
        else:
            rate_str = f"{r['rate']:.5f}"
            lines.append(
                f"{badge} {r['color']} *{r['platform']}*{live_tag}\n"
                f"   `1 KRW = {rate_str} {to_currency}`  ·  {speed}\n"
                f"   _₩1,000,000 → {to_currency} {ref_1m}_"
            )

        lines.append("")   # blank line between rows

    lines.append(_DIVIDER)

    # ── Savings callout ───────────────────────────────────
    if show_amounts and amount_krw > 0 and len(sorted_rates) >= 2:
        saving = best["recipient_amount"] - worst["recipient_amount"]
        if saving > 0.01:
            lines.append(
                _SAVINGS.get(lang, _SAVINGS["en"]).format(
                    saving=_fmt(saving, 2), currency=to_currency
                )
            )

    lines.append(_DISCLAIMER.get(lang, _DISCLAIMER["en"]))
    return "\n".join(lines)
