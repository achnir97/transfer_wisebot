# 🌉 BRIDGE Telegram Bot

> AI-powered remittance comparison bot for foreign workers in South Korea.
> Compare rates from IME, Wise, Hana Bank, Western Union, Remitly, and Prabhu Money.
> Earn referral commissions when users click through to send money.

---

## 🚀 Launch in 15 Minutes

### Step 1 — Create Your Bot (2 minutes)

1. Open Telegram and search for **@BotFather**
2. Send: `/newbot`
3. Name it: `Bridge - 한국 송금 비교` (or your preferred name)
4. Username: `BridgeRemittanceBot` (or similar)
5. Copy the **API token** BotFather gives you

### Step 2 — Get API Keys (5 minutes)

**Anthropic (required for AI responses):**
- Go to https://console.anthropic.com
- Create account → API Keys → Create Key
- Free tier is enough for MVP

**ExchangeRate-API (recommended for live rates):**
- Go to https://www.exchangerate-api.com
- Sign up free → copy your API key
- Free tier: 1,500 requests/month (plenty for MVP)

### Step 3 — Set Up the Bot (5 minutes)

```bash
# Clone or copy the bot files to your machine

# Install Python 3.10+ if not installed
# Mac: brew install python3
# Ubuntu: sudo apt install python3 python3-pip

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
nano .env   # Fill in your keys
```

Your `.env` should look like:
```
TELEGRAM_BOT_TOKEN=7234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
EXCHANGE_RATE_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
REFERRAL_SALT=change_this_to_something_random_32chars
```

### Step 4 — Launch (1 minute)

```bash
python bot.py
```

You should see:
```
2026-03-03 10:00:00 | INFO | __main__ | 🚀 Bridge Bot starting...
```

Open Telegram, find your bot, send `/start` — it works! 🎉

---

## 📱 Bot Commands

| Command | What it does |
|---------|-------------|
| `/start` | Welcome + language selection |
| `/send` | Compare rates for amount you want to send |
| `/rates` | Show current rates (no amount needed) |
| `/alert` | Set rate alert for target rate |
| `/language` | Change language |
| `/help` | Show all commands |

---

## 💰 How You Earn Money

Every time a user taps **"Send Here → IME Nepal"** (or any platform button):

1. Bot generates a **tracked referral URL** with your affiliate code
2. User completes their transfer on that platform's website
3. Platform pays Bridge a **referral commission** (0.3–1.5%)

**Track your earnings:**
- Check `referral_clicks.json` to see all clicks
- Check `users.json` to see all users

---

## 🔄 Keep Bot Running 24/7

**Option A — Free (Railway.app):**
```bash
# 1. Push code to GitHub
# 2. Go to railway.app
# 3. Deploy from GitHub repo
# 4. Add environment variables in Railway dashboard
# Done — runs free forever
```

**Option B — VPS (DigitalOcean $4/month):**
```bash
# On your VPS:
pip install -r requirements.txt
cp .env.example .env && nano .env

# Run with PM2 (auto-restart on crash):
npm install -g pm2
pm2 start bot.py --interpreter python3 --name bridge-bot
pm2 startup  # Auto-start on reboot
pm2 save
```

---

## 📊 Monitor Your Bot

Check bot statistics anytime:
```bash
python -c "
from users import get_stats
from referral import get_referral_stats
import json
print('USERS:', json.dumps(get_stats(), indent=2))
print('CLICKS:', json.dumps(get_referral_stats(), indent=2))
"
```

---

## 🌐 Share in Facebook Groups

Once running, share this message in Nepali Facebook groups in Korea:

**Nepali (copy-paste):**
```
🇰🇷 कोरियाबाट पैसा पठाउनु छ? 💸

Bridge Bot ले IME, Wise, Hana Bank, Western Union सबैको दर एकैपटक देखाउँछ!
सबैभन्दा राम्रो दरमा पठाउनुस् — प्रति महिना ₩30,000+ बचत गर्नुस्!

👉 Telegram: @YourBotUsername

निःशुल्क। तपाईंको पैसा छुँदैन। केवल तुलना गर्छ। ✅
```

**Target groups:**
- Nepali in Korea 한국 네팔인
- EPS Korea Nepali Workers
- Korean Nepali Community
- 한국 베트남 커뮤니티 (Vietnamese)

---

## 📈 Upgrade Path

When you hit these milestones, upgrade accordingly:

| Users | Action |
|-------|--------|
| 200 | Sign Wise affiliate program (wise.com/partners) |
| 500 | Sign IME Nepal direct partnership |
| 1,000 | Move from JSON storage to PostgreSQL |
| 2,000 | Build the full React Native app |
| 5,000 | Apply K-Startup Grand Challenge |

---

## 🤝 Affiliate Program Sign-ups (Do This Today)

| Platform | Sign up link | Commission |
|----------|-------------|------------|
| Wise | wise.com/partners | $10-25 per new user |
| Remitly | remitly.com/affiliate | $10-25 per new user |
| Coupang | partners.coupang.com | 3-8% per sale |

---

## ⚙️ File Structure

```
bridge-bot/
├── bot.py          — Main bot logic, all command handlers
├── rates.py        — Live rate fetching from 6 platforms
├── ai.py           — Claude AI integration
├── users.py        — User data storage (JSON → upgrade to Postgres)
├── referral.py     — Affiliate link generation + click tracking
├── requirements.txt
├── .env.example    — Copy to .env and fill your keys
├── .env            — Your actual keys (NEVER commit this)
├── users.json      — User database (auto-created)
├── referral_clicks.json — Click tracking (auto-created)
├── rate_cache.json — Rate cache (auto-created)
└── bridge_bot.log  — Bot logs (auto-created)
```

---

## 🆘 Troubleshooting

**Bot not responding:**
- Check `bridge_bot.log` for errors
- Verify `TELEGRAM_BOT_TOKEN` is correct in `.env`
- Make sure bot is running: `python bot.py`

**Rates showing wrong:**
- Check `EXCHANGE_RATE_API_KEY` is set
- Delete `rate_cache.json` to force refresh
- Check `bridge_bot.log` for rate fetch errors

**AI responses not working:**
- Verify `ANTHROPIC_API_KEY` is set correctly
- Check you have credits at console.anthropic.com
- Bot still works without AI — just uses fallback messages

---

Built with ❤️ for foreign workers in South Korea.
