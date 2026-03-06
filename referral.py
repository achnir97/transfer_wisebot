"""
referral.py — Affiliate link generation and click tracking
============================================================
Generates tracked referral URLs and logs clicks.
This is how Bridge earns revenue — every click is a potential commission.
"""

import json
import os
import logging
import hashlib
import time
from datetime import datetime

logger = logging.getLogger(__name__)
CLICKS_FILE = "referral_clicks.json"

# ─── AFFILIATE URL TEMPLATES ──────────────────────────────
# Replace these with your actual affiliate URLs once approved.
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

    If TRACKING_BASE_URL is set in the environment, the link goes through
    the tracker.py redirect server — this gives REAL click data (user must
    tap the button for a click to be logged).

    Without TRACKING_BASE_URL the link goes directly to the affiliate URL
    (intent is logged by log_click() when comparison is shown instead).
    """
    uid_hash      = _hash_user_id(user_id)
    tracking_base = os.getenv("TRACKING_BASE_URL", "").rstrip("/")

    if tracking_base:
        # Route through redirect proxy → real click tracking
        slug = platform.lower().replace(" ", "-")
        return (
            f"{tracking_base}/go/{slug}"
            f"?uid={uid_hash}&amt={amount}&cur={currency}"
        )

    # Direct affiliate URL with UTM params (fallback — no server needed)
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
    Log a referral click for commission tracking.

    click_type:
      "actual" — user tapped the Send Here button (real intent)
      "intent" — comparison was shown (kept for backwards compat)
    """
    clicks = _load_clicks()

    entry = {
        "user_id_hash": _hash_user_id(user_id),
        "platform":     platform,
        "amount_krw":   amount,
        "currency":     currency,
        "click_type":   click_type,
        "clicked_at":   datetime.now().isoformat(),
        "date":         datetime.now().strftime("%Y-%m-%d"),
    }

    clicks.append(entry)
    _save_clicks(clicks)

    logger.info(
        f"Referral {click_type} click | platform={platform} | "
        f"amount={amount} KRW | currency={currency}"
    )


def get_referral_stats() -> dict:
    """Get referral stats for revenue tracking."""
    clicks      = _load_clicks()
    actual      = [c for c in clicks if c.get("click_type", "actual") == "actual"]
    by_platform = {}
    by_date     = {}

    for c in actual:
        p = c.get("platform", "unknown")
        d = c.get("date", "unknown")
        by_platform[p] = by_platform.get(p, 0) + 1
        by_date[d]     = by_date.get(d, 0) + 1

    return {
        "total_clicks":        len(actual),
        "total_clicks_all":    len(clicks),
        "by_platform":         by_platform,
        "by_date":             dict(sorted(by_date.items(), reverse=True)[:30]),
    }


def _hash_user_id(user_id: int) -> str:
    """One-way hash user ID for privacy-safe tracking."""
    salt = os.getenv("REFERRAL_SALT", "bridge_default_salt_change_me")
    return hashlib.sha256(f"{salt}{user_id}".encode()).hexdigest()[:16]


def _load_clicks() -> list:
    if os.path.exists(CLICKS_FILE):
        try:
            with open(CLICKS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_clicks(clicks: list) -> None:
    try:
        with open(CLICKS_FILE, "w") as f:
            json.dump(clicks, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving clicks: {e}")
