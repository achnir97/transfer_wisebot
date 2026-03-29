# Bridge Bot — Claude Code Context

## What This Project Does
Multi-platform remittance comparison bot for foreign workers in South Korea. Compares live exchange rates from GME and Hanpass, generates affiliate referral links, tracks clicks, and earns commissions. Runs on Telegram, WhatsApp, and Facebook Messenger simultaneously.

## File Map

| File | Role |
|------|------|
| `bot.py` | Telegram entry point — polling loop, ConversationHandler states |
| `handler_core.py` | **The brain** — platform-agnostic logic shared by all platforms |
| `rates.py` | Live rate aggregator with 30-min cache |
| `fetchers.py` | Async HTTP clients for GME and Hanpass APIs |
| `users.py` | Supabase user profiles (language, alerts, click history) |
| `referral.py` | Affiliate link generation + click tracking |
| `web.py` | FastAPI webhook server (WhatsApp + Messenger routes) |
| `whatsapp.py` | WhatsApp Cloud API webhook handler |
| `messenger.py` | Facebook Messenger webhook handler |
| `tracker.py` | Standalone click redirect service (separate Railway deployment) |
| `db.py` | Supabase singleton client |
| `ai.py` | Static fallback response handler (no live AI yet) |
| `supabase_schema.sql` | DB schema: users, rate_alerts, referral_clicks tables |

## Tech Stack
- Python 3.11.8, fully async/await
- `python-telegram-bot[job-queue]==21.3`
- FastAPI + Uvicorn for webhooks
- Supabase (PostgreSQL) for all persistence
- HTTPX for async HTTP
- Deployed on Railway (worker + web service)

## Supported Languages
8 languages: Nepali, Vietnamese, English, Tagalog, Indonesian, Uzbek, Thai, Chinese

## Architecture Rule — Most Important
`handler_core.py` is the single brain. **All platform-specific files (bot.py, whatsapp.py, messenger.py) must route through handler_core.py.** Never put business logic directly in platform files.

## Coding Conventions
- All I/O must be `async/await` — never use blocking calls (requests, time.sleep)
- Use Supabase for ALL persistence — never write to JSON files for user/click/alert data
- `rate_cache.json` is the only acceptable JSON file (cache layer for API responses)
- Error handling: log errors with context, return user-friendly fallback message, never crash the bot
- Environment variables only via `python-dotenv` — never hardcode credentials
- Use `httpx.AsyncClient` with timeouts for all external API calls

## Always Do This
- Before touching `handler_core.py`: consider impact on ALL three platforms (Telegram, WhatsApp, Messenger)
- When adding a new rate provider: add to both `fetchers.py` (API client) and `rates.py` (aggregator)
- When adding a new language: update the language picker in `handler_core.py` AND `bot.py` ConversationHandler
- Never commit `.env` — check `.gitignore` is respected
- After schema changes: update `supabase_schema.sql` to match

## Deployment
- **Railway Worker:** `python3 bot.py` — Telegram polling
- **Railway Web:** `uvicorn web:app --host 0.0.0.0 --port $PORT` — Meta webhooks
- **Optional Railway Web:** `uvicorn tracker:app ...` — click tracker (separate service)
- Shared Supabase DB across all services

## Common Commands
```bash
# Run bot locally
source .venv/bin/activate && python bot.py

# Run webhook server locally
source .venv/bin/activate && uvicorn web:app --reload --port 8000

# Check Supabase connection
source .venv/bin/activate && python check_supabase.py

# Syntax check a file
python -m py_compile <file.py>
```

## Conversation States (bot.py)
- `0` = CHOOSING_LANGUAGE
- `1` = ENTERING_AMOUNT
- `2` = ENTERING_ALERT_RATE
- `3` = MAIN_MENU
