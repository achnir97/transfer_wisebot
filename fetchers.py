"""
fetchers.py — Async provider API clients
=========================================
All three endpoints confirmed via DevTools network interception.

GME:     POST https://online.gmeremit.com/ExchangeRate.aspx          (form-data)
Hanpass: POST https://app.hanpass.com/app/v1/remittance/get-cost     (JSON, memberSeq=1)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────

GME_COUNTRY_NAMES = {
    "PHP": "Philippines", "NPR": "Nepal",      "VND": "Vietnam",
    "IDR": "Indonesia",   "BDT": "Bangladesh", "PKR": "Pakistan",
    "LKR": "Sri Lanka",   "MYR": "Malaysia",   "USD": "USA",
    "CNY": "China",       "KHR": "Cambodia",   "MMK": "Myanmar",
    "THB": "Thailand",    "MNT": "Mongolia",   "UZS": "Uzbekistan",
    "INR": "India",       "KGS": "Kyrgyzstan", "KZT": "Kazakhstan",
}

HANPASS_COUNTRY_CODES = {
    "PHP": "PH", "NPR": "NP", "VND": "VN", "IDR": "ID",
    "BDT": "BD", "PKR": "PK", "LKR": "LK", "MYR": "MY",
    "USD": "US", "CNY": "CN", "KHR": "KH", "MMK": "MM",
    "THB": "TH", "MNT": "MN", "UZS": "UZ", "INR": "IN",
    "KGS": "KG", "KZT": "KZ",
}

SPEED_MAP = {
    "15MINS": "~15 minutes",
    "1HOUR":  "~1 hour",
    "SAMEDAY":"same day",
    "1DAY":   "next day",
    "2DAY":   "2 days",
}


# ── Helpers ───────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_num(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

def _markup(rate: float, mid: float) -> Optional[float]:
    if not rate or not mid:
        return None
    return round(abs(mid - rate) / mid * 100, 4)


# ── RateFetcher ───────────────────────────────────────────────

class RateFetcher:
    """
    Async fetcher that calls all three providers in parallel.
    Uses a shared httpx.AsyncClient with connection pooling.
    """

    def __init__(self, timeout: int = 12):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RateBot/1.0)"},
        )

    async def close(self):
        await self._client.aclose()

    # ── Public ────────────────────────────────────────────────

    async def fetch_all(
        self,
        from_currency: str = "KRW",
        to_currency:   str = "PHP",
        send_amount:   int = 1_000_000,
    ) -> dict:
        """
        Fire all three provider requests in parallel.
        Returns a dict keyed by provider slug.
        Failed providers return an error key — never raises.
        """
        results = await asyncio.gather(
            self._fetch_gme(send_amount, from_currency, to_currency),
            self._fetch_hanpass(send_amount, from_currency, to_currency),
            return_exceptions=True,
        )

        def _unwrap(provider_name: str, result) -> dict:
            if isinstance(result, Exception):
                log.error(f"{provider_name} raised unexpected exception: {result}")
                return {"provider": provider_name, "error": str(result)}
            return result

        gme_raw     = _unwrap("GME",     results[0])
        hanpass_raw = _unwrap("Hanpass", results[1])

        return {
            "from_currency": from_currency,
            "to_currency":   to_currency,
            "send_amount":   send_amount,
            "gme":           gme_raw,
            "hanpass":       hanpass_raw,
            "fetched_at":    _now(),
        }

    # ── GME ──────────────────────────────────────────────────

    async def _fetch_gme(
        self,
        send_amount: int,
        from_cur: str,
        to_cur: str,
        delivery_method: int = 2,
    ) -> dict:
        url = "https://online.gmeremit.com/ExchangeRate.aspx"
        headers = {
            "Accept":           "application/json, text/javascript, */*; q=0.01",
            "Content-Type":     "application/x-www-form-urlencoded",
            "Referer":          "https://online.gmeremit.com/",
            "X-Requested-With": "XMLHttpRequest",
        }
        payload = {
            "method":         "GetExRate",
            "pCurr":          to_cur,
            "pCountryName":   GME_COUNTRY_NAMES.get(to_cur, to_cur),
            "collCurr":       from_cur,
            "deliveryMethod": str(delivery_method),
            "cAmt":           str(send_amount),
            "pAmt":           "",
            "cardOnline":     "false",
            "calBy":          "C",
        }
        try:
            resp = await self._client.post(url, data=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            if str(data.get("errorCode", "0")) != "0":
                return {"provider": "GME", "error": data.get("msg", "API error")}

            rate            = _parse_num(data.get("exRate"))
            bank_rate       = _parse_num(data.get("bankRate"))
            fee_krw         = _parse_num(data.get("bankFee"))
            service_charge  = _parse_num(data.get("scCharge"))
            recipient       = _parse_num(data.get("pAmt"))
            bank_payout     = _parse_num(data.get("bankPayout"))
            savings_vs_bank = _parse_num(data.get("bankSave"))
            total_collected = _parse_num(data.get("collAmt"))
            total_fee       = (fee_krw or 0) + (service_charge or 0)

            log.info(f"GME     {from_cur}→{to_cur}  rate={rate}  fee={total_fee}  recipient={recipient}")
            return {
                "provider":                "GME",
                "exchange_rate":           rate,
                "mid_market_rate":         bank_rate,
                "markup_percent":          _markup(rate, bank_rate),
                "transfer_fee_krw":        total_fee,
                "bank_fee_krw":            fee_krw,
                "service_charge_krw":      service_charge,
                "recipient_gets":          recipient,
                "bank_payout_comparison":  bank_payout,
                "savings_vs_bank_krw":     savings_vs_bank,
                "total_collected_krw":     total_collected,
                "delivery_method":         delivery_method,
                "transfer_speed":          "1–2 days",
                "collected_at":            _now(),
                "source":                  "api",
            }
        except Exception as e:
            log.error(f"GME fetch error: {e}")
            return {"provider": "GME", "error": str(e)}

    # ── Hanpass ──────────────────────────────────────────────

    async def _fetch_hanpass(
        self,
        send_amount: int,
        from_cur: str,
        to_cur: str,
    ) -> dict:
        url = "https://app.hanpass.com/app/v1/remittance/get-cost"
        headers = {
            "Accept":       "application/json",
            "Content-Type": "application/json",
            "Origin":       "https://www.hanpass.com",
            "Referer":      "https://www.hanpass.com/",
        }
        payload = {
            "fromCurrencyCode":  from_cur,
            "inputAmount":       str(send_amount),
            "inputCurrencyCode": from_cur,
            "lang":              "en",
            "memberSeq":         "1",
            "toCountryCode":     HANPASS_COUNTRY_CODES.get(to_cur, to_cur[:2]),
            "toCurrencyCode":    to_cur,
        }
        try:
            resp = await self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            if str(data.get("resultCode", "0")) != "0":
                return {"provider": "Hanpass", "error": data.get("resultMessage", "API error")}

            rate             = data.get("exchangeRate")
            fee_krw          = data.get("transferFee")
            recipient        = data.get("toAmount")
            total_collected  = data.get("depositAmountIncludingFee")
            autosend_fee     = float(data.get("autosendFee", 0) or 0)
            mid_rate_reverse = data.get("reverse_exchange_origin_rate")
            speed_code       = data.get("requiredTimeCode", "")
            rate_expr        = data.get("exchangeRateExpr")
            min_limit        = data.get("minAmountLimit")
            max_limit        = data.get("maxAmountLimit")

            mid_rate  = (1 / mid_rate_reverse) if mid_rate_reverse else None
            total_fee = (fee_krw or 0) + autosend_fee

            log.info(f"Hanpass {from_cur}→{to_cur}  rate={rate}  fee={total_fee}  speed={speed_code}")
            return {
                "provider":            "Hanpass",
                "exchange_rate":       rate,
                "mid_market_rate":     mid_rate,
                "markup_percent":      _markup(rate, mid_rate),
                "transfer_fee_krw":    total_fee,
                "recipient_gets":      recipient,
                "total_collected_krw": total_collected,
                "transfer_speed":      SPEED_MAP.get(speed_code, speed_code),
                "rate_expression":     rate_expr,
                "min_send_krw":        min_limit,
                "max_send_krw":        max_limit,
                "collected_at":        _now(),
                "source":              "api",
            }
        except Exception as e:
            log.error(f"Hanpass fetch error: {e}")
            return {"provider": "Hanpass", "error": str(e)}
