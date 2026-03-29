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
    "LKR": "Sri Lanka",   "MYR": "Malaysia",   "USD": "United States",
    "CNY": "China",       "KHR": "Cambodia",   "MMK": "Myanmar",
    "THB": "Thailand",    "MNT": "Mongolia",   "UZS": "Uzbekistan",
    "INR": "India",       "KGS": "Kyrgyzstan", "KZT": "Kazakhstan",
}

# GME requires delivery_method=1 (wire) for USD; default is 2 (bank transfer)
GME_DELIVERY_METHODS = {
    "USD": 1,
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

# ── CrossEnf rate key map ─────────────────────────────────
# Format: "COUNTRY_CODE:CURRENCY_CODE"
# platform_id=258 is the Korea (KRW) platform — confirmed from DevTools
# CrossEnf: platform_id determines the destination currency.
# Each platform_id is a Korea-KRW corridor to the destination country.
# Confirmed by scanning platform IDs 200-310 via DevTools.
CROSSENF_PLATFORM_IDS = {
    "NPR": "258",   # NP:NPR  — confirmed original
    "VND": "267",   # VN:VND
    "PHP": "272",   # PH:PHP
    "IDR": "248",   # ID:IDR
    "THB": "268",   # TH:THB
    "BDT": "252",   # BD:BDT
    "USD": "244",   # UZ:USD  — best USD rate among available USD platforms
    "CNY": "241",   # CN:CNY
    "MNT": "250",   # MN:MNT
    "UZS": "262",   # UZ:UZS
    "MMK": "263",   # MM:MMK
    "LKR": "255",   # LK:LKR
    "PKR": None,    # Not found — skip
    "KHR": None,    # Not available on CrossEnf
}

# ── E9Pay country codes ───────────────────────────────────
E9PAY_COUNTRY_CODES = {
    "NPR": "NP", "VND": "VN", "PHP": "PH", "IDR": "ID",
    "THB": "TH", "BDT": "BD", "USD": "US", "CNY": "CN",
    "MNT": "MN", "UZS": "UZ", "KHR": "KH", "MMK": "MM",
    "LKR": "LK", "PKR": "PK",
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
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
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
        Fire all provider requests in parallel.
        Returns a dict keyed by provider slug.
        Failed providers return an error key — never raises.
        """
        results = await asyncio.gather(
            self._fetch_gme(send_amount, from_currency, to_currency),
            self._fetch_hanpass(send_amount, from_currency, to_currency),
            self._fetch_crossenf(send_amount, from_currency, to_currency),
            self._fetch_e9pay(send_amount, from_currency, to_currency),
            return_exceptions=True,
        )

        def _unwrap(provider_name: str, result) -> dict:
            if isinstance(result, Exception):
                log.error(f"{provider_name} raised unexpected exception: {result}")
                return {"provider": provider_name, "error": str(result)}
            return result

        gme_raw      = _unwrap("GME",      results[0])
        hanpass_raw  = _unwrap("Hanpass",  results[1])
        crossenf_raw = _unwrap("CrossEnf", results[2])
        e9pay_raw    = _unwrap("E9Pay",    results[3])

        return {
            "from_currency": from_currency,
            "to_currency":   to_currency,
            "send_amount":   send_amount,
            "gme":           gme_raw,
            "hanpass":       hanpass_raw,
            "crossenf":      crossenf_raw,
            "e9pay":         e9pay_raw,
            "fetched_at":    _now(),
        }

    # ── GME ──────────────────────────────────────────────────

    async def _fetch_gme(
        self,
        send_amount: int,
        from_cur: str,
        to_cur: str,
        delivery_method: int = None,
    ) -> dict:
        if delivery_method is None:
            delivery_method = GME_DELIVERY_METHODS.get(to_cur, 2)
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

    # ── CrossEnf ─────────────────────────────────────────

    async def _fetch_crossenf(
        self,
        send_amount: int,
        from_cur: str,
        to_cur: str,
    ) -> dict:
        """
        Fetch live rate from Cross Remittance (crossenf.com).
        GET request — platform_id determines the destination currency.
        No auth required.
        """
        platform_id = CROSSENF_PLATFORM_IDS.get(to_cur)
        if not platform_id:
            return {"provider": "CrossEnf", "error": f"Unsupported currency: {to_cur}"}

        url = "https://crossenf.com/v2/outbound/quote/"
        params = {
            "platform_id":      platform_id,
            "quote_type":       "send",
            "sending_amount":   str(send_amount),
            "receiving_amount": "null",
            "use_max_point":    "true",
            "deposit_type":     "Manual",
            "apply_user_limit": "0",
            "is_home":          "0",
        }
        headers = {
            "Accept":          "application/json",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Origin":          "https://crossenf.com",
            "Referer":         "https://crossenf.com/",
        }

        try:
            resp = await self._client.get(url, params=params, headers=headers, timeout=12)
            resp.raise_for_status()
            outer = resp.json()

            if outer.get("result") != "success":
                return {
                    "provider": "CrossEnf",
                    "error": f"result={outer.get('result')} msg={outer.get('error', '')}",
                }

            data = outer.get("data", {})

            if not data.get("is_avail_transfer", True):
                reason = data.get("unavailable_reason", "transfer unavailable")
                return {"provider": "CrossEnf", "error": f"Transfer unavailable: {reason}"}

            rate      = _parse_num(data.get("service_rate"))
            fee       = _parse_num(data.get("fee"))
            recipient = _parse_num(data.get("receiving_amount"))
            pay_amt   = _parse_num(data.get("pay_amount"))
            currency  = data.get("currency", to_cur)

            if currency != to_cur:
                return {"provider": "CrossEnf", "error": f"Currency mismatch: requested {to_cur} but got {currency}"}

            if not rate or float(rate) <= 0:
                log.warning(f"CrossEnf: no rate in response. data keys: {list(data.keys())}")
                return {"provider": "CrossEnf", "error": "No rate in response"}

            # CrossEnf's service_rate is KRW-per-destination-currency (inverted).
            # Fee is charged on TOP of the send amount (pay_amount = send + fee).
            # To work with our formula (send - fee) * exchange_rate = recipient_gets,
            # we compute an effective rate: recipient / (send_amount - fee).
            fee_krw = int(float(fee)) if fee else 0
            net_send = send_amount - fee_krw
            if recipient and net_send > 0:
                effective_rate = round(float(recipient) / net_send, 6)
            else:
                effective_rate = round(1.0 / float(rate), 6)

            log.info(
                f"CrossEnf {from_cur}→{to_cur}  "
                f"effective_rate={effective_rate}  fee=₩{fee_krw}  recipient={recipient}  pays=₩{pay_amt}"
            )

            return {
                "provider":           "CrossEnf",
                "exchange_rate":      effective_rate,
                "mid_market_rate":    None,
                "markup_percent":     None,
                "transfer_fee_krw":   fee_krw,
                "recipient_gets":     float(recipient) if recipient else None,
                "total_pay_krw":      float(pay_amt) if pay_amt else None,
                "transfer_speed":     "same day",
                "collected_at":       _now(),
                "source":             "live",
            }

        except Exception as e:
            log.error(f"CrossEnf fetch error: {type(e).__name__}: {e}")
            return {"provider": "CrossEnf", "error": str(e)}

    # ── E9Pay ─────────────────────────────────────────────

    async def _fetch_e9pay(
        self,
        send_amount: int,
        from_cur: str,
        to_cur: str,
    ) -> dict:
        """
        Fetch live rate from E9Pay (e9pay.co.kr).
        POST form-data, response wraps data as a stringified JSON string.
        Only NPR is confirmed to work — all others return HTTP 500.
        """
        import json as _json

        E9PAY_SUPPORTED = {"NPR"}
        if to_cur not in E9PAY_SUPPORTED:
            return {"provider": "E9Pay", "error": f"Unsupported currency: {to_cur}"}

        url = "https://www.e9pay.co.kr/cmm/calcExchangeRate.do"
        headers = {
            "Accept":        "*/*",
            "Content-Type":  "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin":        "https://www.e9pay.co.kr",
            "Referer":       "https://www.e9pay.co.kr/",
            "Cache-Control": "no-cache",
            "Pragma":        "no-cache",
        }
        payload = {
            "DEFRAY_AMOUNT":          str(send_amount),
            "SEND_NATN_COD":          "KR",
            "CRNCY_COD":              from_cur,
            "RCVER_EXPECT_NATN_COD":  E9PAY_COUNTRY_CODES.get(to_cur, "NP"),
            "RCVER_EXPECT_CRNCY_COD": to_cur,
            "SIMULATION_YN":          "Y",
            "OVSE_FEE_PROMOTION_YN":  "N",
            "LANG_COD":               "",
        }

        try:
            resp = await self._client.post(url, data=payload, headers=headers, timeout=12)
            resp.raise_for_status()
            outer = resp.json()

            if outer.get("responseCode") != "S":
                return {
                    "provider": "E9Pay",
                    "error": f"responseCode={outer.get('responseCode')} {outer.get('responseMsg', '')}",
                }

            # data is a stringified JSON inside the outer JSON — parse twice
            raw  = outer.get("data", "")
            data = _json.loads(raw) if isinstance(raw, str) else raw

            # EX_RATE is a formatted string ("1,000 KRW = 100.1 NPR") — not parseable directly.
            # Use RCVER_EXPECT_RECPT_AMOUNT / LAST_REMIT_AMOUNT as the effective rate.
            # Validate returned currency matches what we requested (KHR returns USD data).
            returned_cur = data.get("RCVER_EXPECT_CRNCY_COD", to_cur)
            if returned_cur and returned_cur != to_cur:
                return {"provider": "E9Pay", "error": f"Currency mismatch: requested {to_cur} got {returned_cur}"}

            recipient  = _parse_num(data.get("RCVER_EXPECT_RECPT_AMOUNT"))
            sent_amt   = _parse_num(data.get("LAST_REMIT_AMOUNT"))
            fee        = _parse_num(data.get("CALCU_REMIT_FEE") or data.get("REMIT_FEE"))

            if not recipient or not sent_amt or float(sent_amt) <= 0:
                log.warning(
                    f"E9Pay: amount fields not found. Keys: {list(data.keys())} "
                    f"| sample: { {k: v for k, v in list(data.items())[:6]} }"
                )
                return {"provider": "E9Pay", "error": "Amount fields not found — check Railway logs"}

            # Effective rate: recipient / (sent - fee), compatible with format_comparison formula
            fee_krw    = int(float(fee)) if fee else 0
            net_sent   = float(sent_amt) - fee_krw
            rate_eff   = round(float(recipient) / net_sent, 6) if net_sent > 0 else 0

            log.info(f"E9Pay {from_cur}→{to_cur}  rate={rate_eff}  fee=₩{fee_krw}  recipient={recipient}")

            return {
                "provider":         "E9Pay",
                "exchange_rate":    rate_eff,
                "mid_market_rate":  None,
                "markup_percent":   None,
                "transfer_fee_krw": fee_krw,
                "recipient_gets":   float(recipient),
                "transfer_speed":   "same day",
                "collected_at":     _now(),
                "source":           "live",
            }

        except _json.JSONDecodeError as e:
            log.error(f"E9Pay JSON error: {e} | raw={str(outer.get('data', ''))[:200]}")
            return {"provider": "E9Pay", "error": f"JSON parse: {e}"}
        except Exception as e:
            log.error(f"E9Pay fetch error: {type(e).__name__}: {e}")
            return {"provider": "E9Pay", "error": str(e)}
