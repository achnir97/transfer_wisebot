"""
rates.py — Live exchange rate aggregator
=========================================
GME and Hanpass: real rates fetched directly from their APIs via fetchers.py
Other platforms: mid-market rate + known spread/fee estimates (fallback comparison)

Platform currency coverage:
  IME Nepal / Prabhu Money — NPR only
  GME, Hanpass, Wise, Hana Bank, Western Union, Remitly — all supported currencies
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

import httpx

from fetchers import RateFetcher

logger = logging.getLogger(__name__)


# ─── Platform configs ─────────────────────────────────────

PLATFORMS = {
    "GME": {
        "color":          "🟤",
        "speed":          "1-2일 / 1-2 days",
        "url":            "https://online.gmeremit.com",
        "affiliate_base": "https://online.gmeremit.com",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY"],
        "real_api":       True,
    },
    "Hanpass": {
        "color":          "🔵",
        "speed":          "당일 / Same day",
        "url":            "https://www.hanpass.com",
        "affiliate_base": "https://www.hanpass.com",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY"],
        "real_api":       True,
    },
    "IME Nepal": {
        "color":          "🟢",
        "speed":          "당일 / Same day",
        "url":            "https://www.imenepal.com",
        "affiliate_base": "https://www.imenepal.com/?ref=bridge",
        "currencies":     ["NPR"],
        "real_api":       False,
    },
    "Prabhu Money": {
        "color":          "🟣",
        "speed":          "당일 / Same day",
        "url":            "https://prabhupay.com",
        "affiliate_base": "https://prabhupay.com/?ref=bridge",
        "currencies":     ["NPR"],
        "real_api":       False,
    },
    "Wise": {
        "color":          "🔵",
        "speed":          "1-2일 / 1-2 days",
        "url":            "https://wise.com",
        "affiliate_base": "https://wise.com/invite/u/bridge",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY"],
        "real_api":       False,
    },
    "Western Union": {
        "color":          "🟠",
        "speed":          "몇 분 / Minutes",
        "url":            "https://www.westernunion.com",
        "affiliate_base": "https://www.westernunion.com/kr/ko/send-money.html?ref=bridge",
        "currencies":     ["NPR", "VND", "PHP", "IDR", "UZS", "THB", "BDT", "USD", "CNY"],
        "real_api":       False,
    },
    "Remitly": {
        "color":          "🔴",
        "speed":          "다음날 / Next day",
        "url":            "https://remitly.com",
        "affiliate_base": "https://remitly.com/?ref=bridge_bot",
        "currencies":     ["NPR", "PHP", "VND", "IDR", "THB", "BDT", "USD"],
        "real_api":       False,
    },
}

# ─── Typical fees (KRW) for estimated platforms ───────────
PLATFORM_FEES: dict[str, dict] = {
    "IME Nepal":     {"flat": 2000, "percent": 0.000},
    "Prabhu Money":  {"flat": 1800, "percent": 0.000},
    "Wise":          {"flat":    0, "percent": 0.0065},
    "Western Union": {"flat":    0, "percent": 0.0150},
    "Remitly":       {"flat": 2500, "percent": 0.000},
}

# Spread each estimated platform applies on top of mid-market rate
PLATFORM_SPREADS: dict[str, float] = {
    "IME Nepal":     0.9985,
    "Prabhu Money":  0.9990,
    "Wise":          0.9935,
    "Western Union": 0.9850,
    "Remitly":       0.9970,
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


# ─── Mid-market rate sources (for estimated platforms) ────

async def _fetch_open_er(from_c: str, to_c: str) -> Optional[float]:
    """open.er-api.com — free, no key required."""
    try:
        url = f"https://open.er-api.com/v6/latest/{from_c}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r    = await client.get(url)
            data = r.json()
            rate = data.get("rates", {}).get(to_c)
            if rate:
                return float(rate)
    except Exception as e:
        logger.warning(f"open.er-api error: {e}")
    return None


async def _fetch_exchangerate_api(from_c: str, to_c: str) -> Optional[float]:
    """ExchangeRate-API v6 (free tier: 1,500 req/month)."""
    api_key = os.getenv("EXCHANGE_RATE_API_KEY", "")
    if not api_key:
        return None
    try:
        url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_c}/{to_c}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r    = await client.get(url)
            data = r.json()
            if data.get("result") == "success":
                return float(data["conversion_rate"])
    except Exception as e:
        logger.warning(f"ExchangeRate-API error: {e}")
    return None


# ─── Static fallback rates ────────────────────────────────
STATIC_FALLBACK_RATES: dict[tuple, float] = {
    ("KRW", "NPR"): 0.1032,
    ("KRW", "VND"): 17.85,
    ("KRW", "PHP"): 0.0425,
    ("KRW", "IDR"): 11.80,
    ("KRW", "UZS"): 9.85,
    ("KRW", "THB"): 0.0263,
    ("KRW", "BDT"): 0.0803,
    ("KRW", "USD"): 0.00073,
    ("KRW", "CNY"): 0.00525,
}


async def _get_mid_market_rate(from_c: str, to_c: str) -> float:
    """Get mid-market rate for estimated platforms."""
    results = await asyncio.gather(
        _fetch_open_er(from_c, to_c),
        _fetch_exchangerate_api(from_c, to_c),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, float) and r > 0:
            return r

    static = STATIC_FALLBACK_RATES.get((from_c, to_c))
    if static:
        logger.warning(f"Using static fallback rate for {from_c}/{to_c}: {static}")
        return static

    raise ValueError(f"No rate available for {from_c}/{to_c}")


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
    Get comparison rates for all supported platforms.
    GME + Hanpass: real rates from direct API calls.
    Other platforms: mid-market rate + known spreads/fees.
    Returns list sorted best → worst by rate.
    Never raises — falls back to cached or static rates.
    """
    cache_key = _cache_key(from_currency, to_currency)

    if _is_cache_fresh(cache_key):
        logger.info(f"Cache hit: {cache_key}")
        return _rate_cache[cache_key]["rates"]

    try:
        supported = get_platforms_for_currency(to_currency)

        # Fetch real rates (GME/Hanpass) and mid-market in parallel
        fetcher = RateFetcher()
        real_data_task  = fetcher.fetch_all(from_currency, to_currency, send_amount=500_000)
        mid_rate_task   = _get_mid_market_rate(from_currency, to_currency)

        real_data, mid_rate = await asyncio.gather(
            real_data_task, mid_rate_task, return_exceptions=True
        )
        await fetcher.close()

        if isinstance(mid_rate, Exception):
            mid_rate = STATIC_FALLBACK_RATES.get((from_currency, to_currency), 0)
        if isinstance(real_data, Exception):
            real_data = {}

        rates: list[dict] = []

        for platform in supported:
            cfg = PLATFORMS[platform]

            if cfg.get("real_api"):
                # GME or Hanpass — use real API data
                slug    = platform.lower()  # "gme" or "hanpass"
                pdata   = real_data.get(slug, {}) if isinstance(real_data, dict) else {}

                if "error" in pdata or not pdata.get("exchange_rate"):
                    logger.warning(f"{platform} API failed, skipping: {pdata.get('error')}")
                    continue

                rates.append({
                    "platform":       platform,
                    "rate":           round(float(pdata["exchange_rate"]), 6),
                    "fee_flat_krw":   int(pdata.get("transfer_fee_krw") or 0),
                    "fee_percent":    0.0,
                    "speed":          pdata.get("transfer_speed", cfg["speed"]),
                    "color":          cfg["color"],
                    "url":            cfg["url"],
                    "affiliate_base": cfg["affiliate_base"],
                    "recipient_amount": 0,
                    "from_currency":  from_currency,
                    "to_currency":    to_currency,
                    "data_source":    "live",
                })

            else:
                # Estimated platform — mid-market + spread + fee
                if not mid_rate:
                    continue
                spread   = PLATFORM_SPREADS.get(platform, 0.99)
                fee      = PLATFORM_FEES.get(platform, {"flat": 0, "percent": 0.0})
                p_rate   = mid_rate * spread

                rates.append({
                    "platform":       platform,
                    "rate":           round(p_rate, 6),
                    "fee_flat_krw":   fee["flat"],
                    "fee_percent":    fee["percent"],
                    "speed":          cfg["speed"],
                    "color":          cfg["color"],
                    "url":            cfg["url"],
                    "affiliate_base": cfg["affiliate_base"],
                    "recipient_amount": 0,
                    "from_currency":  from_currency,
                    "to_currency":    to_currency,
                    "data_source":    "estimated",
                })

        _rate_cache[cache_key] = {
            "rates":      rates,
            "fetched_at": time.time(),
        }
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


_FEE_LABEL = {
    "ne": "수수료", "vi": "phí",      "en": "fee",
    "tl": "bayad", "id": "biaya",    "uz": "komissiya",
    "th": "ค่าธรรมเนียม", "zh": "手续费",
}

_HEADERS_AMOUNT = {
    "ne": "💸 *₩{amount} → {currency}*", "vi": "💸 *₩{amount} → {currency}*",
    "en": "💸 *₩{amount} → {currency}*", "tl": "💸 *₩{amount} → {currency}*",
    "id": "💸 *₩{amount} → {currency}*", "uz": "💸 *₩{amount} → {currency}*",
    "th": "💸 *₩{amount} → {currency}*", "zh": "💸 *₩{amount} → {currency}*",
}

_HEADERS_RATES = {
    "ne": "📊 *{currency} हालको दरहरू*",      "vi": "📊 *Tỷ giá {currency} hiện tại*",
    "en": "📊 *Current {currency} Rates*",    "tl": "📊 *Kasalukuyang {currency} Rates*",
    "id": "📊 *Kurs {currency} Saat Ini*",    "uz": "📊 *Joriy {currency} kurslari*",
    "th": "📊 *อัตรา {currency} ปัจจุบัน*",   "zh": "📊 *当前 {currency} 汇率*",
}

_SAVINGS = {
    "ne": "\n💡 Bridge प्रयोगले: *+{saving} {currency}* बचत!",
    "vi": "\n💡 Bằng cách so sánh: *+{saving} {currency}* thêm!",
    "en": "\n💡 By comparing: *+{saving} {currency}* extra!",
    "tl": "\n💡 Sa paghahambing: *+{saving} {currency}* dagdag!",
    "id": "\n💡 Dengan membandingkan: *+{saving} {currency}* lebih!",
    "uz": "\n💡 Taqqoslash orqali: *+{saving} {currency}* qo'shimcha!",
    "th": "\n💡 โดยการเปรียบเทียบ: *+{saving} {currency}* เพิ่มขึ้น!",
    "zh": "\n💡 通过比较节省: *+{saving} {currency}*！",
}

_DISCLAIMER = {
    "ne": "\n_Bridge ले तपाईंको पैसा छुँदैन। केवल तुलना गर्छ।_",
    "vi": "\n_Bridge không bao giờ chạm vào tiền của bạn._",
    "en": "\n_Bridge never touches your money. We only compare._",
    "tl": "\n_Hindi kailanman hahawakan ng Bridge ang iyong pera._",
    "id": "\n_Bridge tidak pernah menyentuh uang Anda._",
    "uz": "\n_Bridge hech qachon pulingizga tegmaydi._",
    "th": "\n_Bridge ไม่เคยแตะต้องเงินของคุณ_",
    "zh": "\n_Bridge 从不接触您的钱，只做比较。_",
}

_LIVE_TAG  = " 🟢"   # appended to GME/Hanpass rate lines
_EST_TAG   = " ~"    # appended to estimated rate lines


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
            fee_krw              = r["fee_flat_krw"] + (amount_krw * r["fee_percent"])
            net_krw              = amount_krw - fee_krw
            r["recipient_amount"] = net_krw * r["rate"]
            r["fee_total_krw"]    = fee_krw
        else:
            r["recipient_amount"] = r["rate"]

    sorted_rates = sorted(rates, key=lambda x: x["recipient_amount"], reverse=True)
    best         = sorted_rates[0]
    fee_lbl      = _FEE_LABEL.get(lang, "fee")

    if show_amounts and amount_krw > 0:
        header = _HEADERS_AMOUNT.get(lang, _HEADERS_AMOUNT["en"]).format(
            amount=_fmt(amount_krw, 0), currency=to_currency
        )
    else:
        header = _HEADERS_RATES.get(lang, _HEADERS_RATES["en"]).format(
            currency=to_currency
        )

    lines = [header, ""]

    for i, r in enumerate(sorted_rates):
        badge     = "✅ *BEST*  " if i == 0 else "          "
        is_live   = r.get("data_source") == "live"
        live_mark = _LIVE_TAG if is_live else _EST_TAG

        if show_amounts and amount_krw > 0:
            recv = _fmt(r["recipient_amount"], 2)
            fee  = _fmt(r["fee_total_krw"], 0)
            lines.append(
                f"{badge}{r['color']} *{r['platform']}*{live_mark}\n"
                f"   {to_currency} {recv}  |  {fee_lbl} ₩{fee}  |  {r['speed']}"
            )
        else:
            rate_str = f"{r['rate']:.5f}"
            lines.append(
                f"{badge}{r['color']} *{r['platform']}*{live_mark}\n"
                f"   1 KRW = {rate_str} {to_currency}  |  {r['speed']}"
            )

    # Savings callout
    if show_amounts and amount_krw > 0 and len(sorted_rates) >= 2:
        worst  = sorted_rates[-1]
        saving = best["recipient_amount"] - worst["recipient_amount"]
        if saving > 0.01:
            lines.append(
                _SAVINGS.get(lang, _SAVINGS["en"]).format(
                    saving=_fmt(saving, 2), currency=to_currency
                )
            )

    # Legend
    lines.append("\n_🟢 live rate  ~ estimated_")
    lines.append(_DISCLAIMER.get(lang, _DISCLAIMER["en"]))
    return "\n".join(lines)
