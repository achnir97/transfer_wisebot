"""
users.py — User data + rate alert persistence (Supabase)
=========================================================
All data is stored in Supabase PostgreSQL — survives Railway redeploys.

Tables required (run in Supabase SQL Editor):
  users, rate_alerts  — see db schema in plan or README
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from db import get_db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── User functions ───────────────────────────────────────

def save_user(
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    language: str,
    currency: str,
) -> None:
    """Save or update a user record (upsert by user_id)."""
    try:
        db  = get_db()
        now = _now()

        # Preserve created_at if user already exists
        existing = get_user(user_id)
        created_at = existing["created_at"] if existing else now

        db.table("users").upsert({
            "user_id":          user_id,
            "username":         username,
            "full_name":        full_name,
            "language":         language,
            "currency":         currency,
            "created_at":       created_at,
            "last_active":      now,
            "comparison_count": existing["comparison_count"] if existing else 0,
        }).execute()

        logger.info(f"Saved user {user_id} | lang={language} | currency={currency}")
    except Exception as e:
        logger.error(f"save_user error: {e}")


def get_user(user_id: int) -> Optional[dict]:
    """Get a user record by Telegram user ID. Returns None if not found."""
    try:
        db  = get_db()
        res = db.table("users").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"get_user error: {e}")
        return None


def update_user(user_id: int, updates: dict) -> None:
    """Update specific fields for a user."""
    try:
        updates["last_active"] = _now()
        get_db().table("users").update(updates).eq("user_id", user_id).execute()
    except Exception as e:
        logger.error(f"update_user error: {e}")


def increment_comparison(user_id: int) -> None:
    """Track how many times user has compared rates."""
    try:
        db       = get_db()
        existing = get_user(user_id)
        if existing:
            db.table("users").update({
                "comparison_count": existing.get("comparison_count", 0) + 1,
                "last_active":      _now(),
            }).eq("user_id", user_id).execute()
    except Exception as e:
        logger.error(f"increment_comparison error: {e}")


def log_user_click(
    user_id: int,
    platform: str,
    amount: int,
    currency: str,
) -> None:
    """Record that user tapped a Send Here button — stores last 20 clicks."""
    try:
        db       = get_db()
        existing = get_user(user_id)
        if not existing:
            return

        entry = {
            "platform":   platform,
            "amount_krw": amount,
            "currency":   currency,
            "clicked_at": _now(),
        }

        history = existing.get("click_history") or []
        history.append(entry)
        history = history[-20:]   # keep last 20

        db.table("users").update({
            "click_history": history,
            "last_click":    entry,
            "last_active":   _now(),
        }).eq("user_id", user_id).execute()

        logger.info(
            f"User click | user={user_id} | platform={platform} | "
            f"amount={amount} KRW | currency={currency}"
        )
    except Exception as e:
        logger.error(f"log_user_click error: {e}")


def get_stats() -> dict:
    """Get basic user stats for admin monitoring."""
    try:
        db    = get_db()
        users = db.table("users").select("language, currency").execute().data or []

        by_lang:     dict = {}
        by_currency: dict = {}
        for u in users:
            lang     = u.get("language", "unknown")
            currency = u.get("currency", "unknown")
            by_lang[lang]         = by_lang.get(lang, 0) + 1
            by_currency[currency] = by_currency.get(currency, 0) + 1

        return {
            "total_users": len(users),
            "by_language": by_lang,
            "by_currency": by_currency,
        }
    except Exception as e:
        logger.error(f"get_stats error: {e}")
        return {"total_users": 0, "by_language": {}, "by_currency": {}}


# ─── Alert functions ──────────────────────────────────────

def save_alert(user_id: int, currency: str, target_rate: float, lang: str = "en") -> None:
    """Save or overwrite a rate alert for a user+currency pair."""
    try:
        db = get_db()
        # Remove any existing alert for same user+currency
        db.table("rate_alerts").delete().eq("user_id", user_id).eq("currency", currency).execute()
        db.table("rate_alerts").insert({
            "user_id":     user_id,
            "currency":    currency,
            "target_rate": target_rate,
            "lang":        lang,
            "created_at":  _now(),
        }).execute()
        logger.info(f"Alert saved | user={user_id} | currency={currency} | target={target_rate}")
    except Exception as e:
        logger.error(f"save_alert error: {e}")


def get_all_alerts() -> list[dict]:
    """Return all pending rate alerts (used by background job)."""
    try:
        res = get_db().table("rate_alerts").select("*").execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_all_alerts error: {e}")
        return []


def get_user_alerts(user_id: int) -> list[dict]:
    """Return all alerts for a specific user."""
    try:
        res = get_db().table("rate_alerts").select("*").eq("user_id", user_id).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_user_alerts error: {e}")
        return []


def remove_alert(user_id: int, currency: str) -> None:
    """Remove a triggered or cancelled alert."""
    try:
        get_db().table("rate_alerts").delete().eq("user_id", user_id).eq("currency", currency).execute()
        logger.info(f"Alert removed | user={user_id} | currency={currency}")
    except Exception as e:
        logger.error(f"remove_alert error: {e}")


def remove_all_user_alerts(user_id: int) -> int:
    """Remove all alerts for a user. Returns count removed."""
    try:
        existing = get_user_alerts(user_id)
        get_db().table("rate_alerts").delete().eq("user_id", user_id).execute()
        return len(existing)
    except Exception as e:
        logger.error(f"remove_all_user_alerts error: {e}")
        return 0
