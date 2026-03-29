# Pre-Deployment Checklist

Run through this checklist before pushing to Railway. Check each item and report status.

## 1. Syntax Check All Python Files
```bash
python -m py_compile bot.py handler_core.py rates.py fetchers.py users.py referral.py web.py whatsapp.py messenger.py tracker.py db.py ai.py
```
Report any syntax errors. Stop if any file fails.

## 2. Environment Variables
Check `.env.example` against `.env` — verify all required keys are present:
- `TELEGRAM_BOT_TOKEN`
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`
- `MESSENGER_PAGE_ACCESS_TOKEN`, `MESSENGER_VERIFY_TOKEN`
- `REFERRAL_BASE_URL`

Report any missing keys.

## 3. Supabase Schema
- Read `supabase_schema.sql`
- Check that `users.py`, `referral.py` only use columns/tables defined in the schema
- Flag any mismatches (column name changes, new tables not in schema)

## 4. No JSON Persistence for User Data
- Grep for any writes to `.json` files in `users.py`, `referral.py`, `handler_core.py`
- Only `rate_cache.json` writes are acceptable

## 5. No Hardcoded Credentials
```bash
grep -r "sk-\|xoxb-\|Bearer \|password\s*=" --include="*.py" .
```
Flag any hardcoded secrets.

## 6. handler_core.py Platform Neutrality
- Confirm `handler_core.py` has no direct Telegram/WhatsApp/Messenger imports
- All platform-specific code must stay in `bot.py`, `whatsapp.py`, `messenger.py`

## 7. Procfile Check
- Confirm `Procfile` still says `worker: python3 bot.py`
- Confirm `runtime.txt` still says `python-3.11.8`

## 8. Git Status
```bash
git status
git diff --stat
```
- Confirm `.env` is NOT staged
- Show summary of what will be deployed

## Report
Summarize: which checks passed, which failed, and what to fix before deploying.
