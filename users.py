"""
users.py — User data + rate alert persistence
===============================================
JSON file storage for MVP.
Upgrade to PostgreSQL when you hit 1,000 users.
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

USERS_FILE  = "users.json"
ALERTS_FILE = "alerts.json"


# ─── Internal helpers ─────────────────────────────────────

def _load(path: str, default) -> any:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")
    return default


def _save(path: str, data: any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving {path}: {e}")


# ─── User functions ───────────────────────────────────────

def save_user(
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    language: str,
    currency: str,
) -> None:
    """Save or update a user record."""
    users = _load(USERS_FILE, {})
    key = str(user_id)
    users[key] = {
        "user_id":          user_id,
        "username":         username,
        "full_name":        full_name,
        "language":         language,
        "currency":         currency,
        "created_at":       users.get(key, {}).get("created_at", datetime.now().isoformat()),
        "last_active":      datetime.now().isoformat(),
        "comparison_count": users.get(key, {}).get("comparison_count", 0),
    }
    _save(USERS_FILE, users)
    logger.info(f"Saved user {user_id} | lang={language} | currency={currency}")


def get_user(user_id: int) -> Optional[dict]:
    """Get a user record by Telegram user ID."""
    return _load(USERS_FILE, {}).get(str(user_id))


def update_user(user_id: int, updates: dict) -> None:
    """Update specific fields for a user."""
    users = _load(USERS_FILE, {})
    key = str(user_id)
    if key in users:
        users[key].update(updates)
        users[key]["last_active"] = datetime.now().isoformat()
        _save(USERS_FILE, users)


def increment_comparison(user_id: int) -> None:
    """Track how many times user has compared rates."""
    users = _load(USERS_FILE, {})
    key = str(user_id)
    if key in users:
        users[key]["comparison_count"] = users[key].get("comparison_count", 0) + 1
        users[key]["last_active"] = datetime.now().isoformat()
        _save(USERS_FILE, users)


def get_stats() -> dict:
    """Get basic user stats for admin monitoring."""
    users = _load(USERS_FILE, {})
    by_lang: dict     = {}
    by_currency: dict = {}
    for u in users.values():
        lang     = u.get("language", "unknown")
        currency = u.get("currency", "unknown")
        by_lang[lang]         = by_lang.get(lang, 0) + 1
        by_currency[currency] = by_currency.get(currency, 0) + 1

    return {
        "total_users": len(users),
        "by_language": by_lang,
        "by_currency": by_currency,
    }


# ─── Alert functions ──────────────────────────────────────

def save_alert(user_id: int, currency: str, target_rate: float, lang: str = "en") -> None:
    """
    Save or overwrite a rate alert for a user+currency pair.
    Each user can have one alert per currency.
    """
    alerts = _load(ALERTS_FILE, [])

    # Remove any existing alert for same user+currency
    alerts = [
        a for a in alerts
        if not (a["user_id"] == user_id and a["currency"] == currency)
    ]

    alerts.append({
        "user_id":     user_id,
        "currency":    currency,
        "target_rate": target_rate,
        "lang":        lang,
        "created_at":  datetime.now().isoformat(),
    })
    _save(ALERTS_FILE, alerts)
    logger.info(f"Alert saved | user={user_id} | currency={currency} | target={target_rate}")


def get_all_alerts() -> list[dict]:
    """Return all pending rate alerts (used by background job)."""
    return _load(ALERTS_FILE, [])


def get_user_alerts(user_id: int) -> list[dict]:
    """Return all alerts for a specific user."""
    return [a for a in _load(ALERTS_FILE, []) if a["user_id"] == user_id]


def remove_alert(user_id: int, currency: str) -> None:
    """Remove a triggered or cancelled alert."""
    alerts = _load(ALERTS_FILE, [])
    alerts = [
        a for a in alerts
        if not (a["user_id"] == user_id and a["currency"] == currency)
    ]
    _save(ALERTS_FILE, alerts)
    logger.info(f"Alert removed | user={user_id} | currency={currency}")


def remove_all_user_alerts(user_id: int) -> int:
    """Remove all alerts for a user. Returns count removed."""
    alerts = _load(ALERTS_FILE, [])
    before = len(alerts)
    alerts = [a for a in alerts if a["user_id"] != user_id]
    _save(ALERTS_FILE, alerts)
    return before - len(alerts)
