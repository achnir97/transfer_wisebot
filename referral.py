"""
referral.py — Affiliate link generation and click tracking (Supabase)
======================================================================
Generates tracked referral URLs and logs clicks to Supabase.
"""

import os
import logging
import hashlib
from datetime import datetime, timezone

from db import get_db

logger = logging.getLogger(__name__)

# ─── AFFILIATE URL TEMPLATES ──────────────────────────────
AFFILIATE_URLS = {
    "GME":          "https://online.gmeremit.com/?utm_source=bridge_bot&utm_medium=telegram",
    "Hanpass":      "https://www.hanpass.com/?utm_source=bridge_bot&utm_medium=telegram",
    "IME Nepal":    "https://www.imenepal.com/?ref=bridge_bot&utm_source=bridge&utm_medium=telegram",
    "Wise":         "https://wise.com/invite/u/bridge?utm_source=bridge_bot&utm_medium=telegram",
    "Western Union":"https://www.westernunion.com/kr/ko/send-money.html?ref=bridge",
    "Remitly":      "https://remitly.com/?ref=bridge_bot&utm_source=bridge&utm_medium=telegram",
    "Prabhu Money": "https://prabhupay.com/?ref=bridge&utm_source=bridge_bot",
}


def generate_referral_link(
    platform: str,
    user_id: int,
    amount: int,
    currency: str,
) -> str:
    """
    Generate a tracked referral URL for a platform.

    If TRACKING_BASE_URL is set, routes through the redirect server.
    Otherwise uses a direct affiliate URL with UTM params.
    """
    uid_hash      = _hash_user_id(user_id)
    tracking_base = os.getenv("TRACKING_BASE_URL", "").rstrip("/")

    if tracking_base:
        slug = platform.lower().replace(" ", "-")
        return (
            f"{tracking_base}/go/{slug}"
            f"?uid={uid_hash}&amt={amount}&cur={currency}"
        )

    base_url  = AFFILIATE_URLS.get(platform, AFFILIATE_URLS["Wise"])
    separator = "&" if "?" in base_url else "?"
    return (
        f"{base_url}{separator}"
        f"bridge_uid={uid_hash}&bridge_amt={amount}&bridge_cur={currency}"
    )


def log_click(
    user_id: int,
    platform: str,
    amount: int,
    currency: str,
    click_type: str = "actual",
) -> None:
    """
    Log a referral click to Supabase.

    click_type:
      "actual" — user tapped the Send Here button (real intent)
      "intent" — comparison was shown (kept for backwards compat)
    """
    try:
        now = datetime.now(timezone.utc)
        get_db().table("referral_clicks").insert({
            "user_id_hash": _hash_user_id(user_id),
            "platform":     platform,
            "amount_krw":   amount,
            "currency":     currency,
            "click_type":   click_type,
            "clicked_at":   now.isoformat(),
            "date":         now.strftime("%Y-%m-%d"),
        }).execute()

        logger.info(
            f"Referral {click_type} click | platform={platform} | "
            f"amount={amount} KRW | currency={currency}"
        )
    except Exception as e:
        logger.error(f"log_click error: {e}")


def get_referral_stats() -> dict:
    """Get referral stats for revenue tracking (actual clicks only)."""
    try:
        res    = get_db().table("referral_clicks").select("*").eq("click_type", "actual").execute()
        clicks = res.data or []

        by_platform: dict = {}
        by_date:     dict = {}
        for c in clicks:
            p = c.get("platform", "unknown")
            d = c.get("date", "unknown")
            by_platform[p] = by_platform.get(p, 0) + 1
            by_date[d]     = by_date.get(d, 0) + 1

        return {
            "total_clicks":     len(clicks),
            "by_platform":      by_platform,
            "by_date":          dict(sorted(by_date.items(), reverse=True)[:30]),
        }
    except Exception as e:
        logger.error(f"get_referral_stats error: {e}")
        return {"total_clicks": 0, "by_platform": {}, "by_date": {}}


def _hash_user_id(user_id: int) -> str:
    """One-way hash user ID for privacy-safe tracking."""
    salt = os.getenv("REFERRAL_SALT", "bridge_default_salt_change_me")
    return hashlib.sha256(f"{salt}{user_id}".encode()).hexdigest()[:16]
