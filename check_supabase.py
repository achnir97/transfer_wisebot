#!/usr/bin/env python3
"""
check_supabase.py — Verify data is being saved to Supabase
==========================================================
Run: .venv/bin/python check_supabase.py          # Check tables and show data
Run: .venv/bin/python check_supabase.py --seed   # Insert dummy data, then show tables

(Uses the project .venv so supabase is available. Create it with:
  python3 -m venv .venv && .venv/bin/pip install supabase python-dotenv)

Uses SUPABASE_URL and SUPABASE_ANON_KEY from your environment
(.env locally, or copy from Railway Variables for local check).
"""

import os
import sys
import json
from datetime import datetime, timezone

# Load .env so SUPABASE_* are available when run locally
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Dummy user ID used only for test data (not a real Telegram user)
DUMMY_USER_ID = 999999999


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_dummy_data(db):
    """Insert dummy rows into users, rate_alerts, referral_clicks."""
    now = _now()
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("📤 Inserting dummy data...\n")

    # 1. users
    try:
        db.table("users").upsert({
            "user_id": DUMMY_USER_ID,
            "username": "check_supabase_test",
            "full_name": "Dummy User (check_supabase.py)",
            "language": "en",
            "currency": "USD",
            "created_at": now,
            "last_active": now,
            "comparison_count": 0,
        }).execute()
        print("   ✅ users: 1 row (dummy user)")
    except Exception as e:
        print(f"   ❌ users: {e}")

    # 2. rate_alerts
    try:
        db.table("rate_alerts").delete().eq("user_id", DUMMY_USER_ID).execute()
        db.table("rate_alerts").insert({
            "user_id": DUMMY_USER_ID,
            "currency": "USD",
            "target_rate": 1350.5,
            "lang": "en",
            "created_at": now,
        }).execute()
        print("   ✅ rate_alerts: 1 row (USD @ 1350.5)")
    except Exception as e:
        print(f"   ❌ rate_alerts: {e}")

    # 3. referral_clicks
    try:
        db.table("referral_clicks").insert({
            "user_id_hash": "dummy_check_supabase",
            "platform": "Wise",
            "amount_krw": 500000,
            "currency": "USD",
            "click_type": "actual",
            "clicked_at": now,
            "date": now_date,
        }).execute()
        print("   ✅ referral_clicks: 1 row (Wise, 500000 KRW)")
    except Exception as e:
        print(f"   ❌ referral_clicks: {e}")

    print()


def main():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        print("❌ SUPABASE_URL and SUPABASE_ANON_KEY must be set.")
        print("   Locally: use .env or export them.")
        print("   From Railway: copy from Project → Variables.")
        return

    try:
        from db import get_db
        db = get_db()
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return

    print("✅ Connected to Supabase\n")
    print("─" * 50)

    do_seed = "--seed" in sys.argv or "-s" in sys.argv
    if do_seed:
        seed_dummy_data(db)

    tables = [
        ("users", "User records (saved on /start and activity)"),
        ("rate_alerts", "Rate alerts set via /alert"),
        ("referral_clicks", "Clicks on Send Here / referral links"),
    ]
    for table_name, description in tables:
        try:
            res = db.table(table_name).select("*").limit(100).execute()
            data = res.data or []
            print(f"\n📋 {table_name}")
            print(f"   {description}")
            print(f"   Rows found: {len(data)}" + (" (showing first 100)" if len(data) == 100 else ""))
            if data:
                print(f"   Sample (up to 3 rows):")
                for i, row in enumerate(data[:3], 1):
                    preview = {k: (str(v)[:50] + "..." if len(str(v)) > 50 else v) for k, v in row.items()}
                    print(f"      {i}. {json.dumps(preview, default=str)}")
            else:
                print("   (No rows yet — run with --seed to insert dummy data)")
        except Exception as e:
            print(f"\n❌ {table_name}: {e}")
            print("   (Table might not exist — create it in Supabase SQL Editor)")

    print("\n" + "─" * 50)
    if do_seed:
        print("Done. Dummy data was inserted; check Supabase Table Editor to confirm.")
    else:
        print("Done. Run with --seed to insert dummy data and verify writes.")

if __name__ == "__main__":
    main()
