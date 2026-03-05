"""
tracker.py — Click tracking redirect server
============================================
Runs as a separate web service alongside the bot.

When a user taps "Send Here → Wise" in Telegram, they hit this server
FIRST — we log the real click — then they are redirected to the
affiliate URL.  This gives you proof of traffic for affiliate programs.

Deploy on Railway as a Web Service:
  Build command : pip install -r requirements-tracker.txt
  Start command : uvicorn tracker:app --host 0.0.0.0 --port $PORT

Add TRACKING_BASE_URL to your bot's env vars (e.g. https://bridge-tracker.up.railway.app)
and the bot will automatically route all "Send Here" buttons through here.
"""

import json
import os
import logging
from datetime import datetime

from fastapi import FastAPI, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bridge Click Tracker", docs_url=None, redoc_url=None)

CLICKS_FILE = "real_clicks.json"

# ── Affiliate redirect URLs ───────────────────────────────
# Replace placeholders with your REAL affiliate URLs after approval.
# Platform slug = platform name lowercased, spaces → hyphens
REDIRECT_URLS: dict[str, str] = {
    "ime-nepal": (
        "https://www.imenepal.com/"
        "?ref=bridge_bot&utm_source=bridge&utm_medium=telegram&utm_campaign=krw"
    ),
    "prabhu-money": (
        "https://prabhupay.com/"
        "?ref=bridge&utm_source=bridge_bot&utm_medium=telegram"
    ),
    "wise": (
        "https://wise.com/invite/u/bridge"
        "?utm_source=bridge_bot&utm_medium=telegram&utm_campaign=krw"
    ),
    "hana-bank": (
        "https://www.hanabank.com/cont/hana/foreign/foreign01/1265027_115129.do"
        "?ref=bridge&utm_source=bridge_bot"
    ),
    "western-union": (
        "https://www.westernunion.com/kr/ko/send-money.html"
        "?ref=bridge&utm_source=bridge_bot&utm_medium=telegram"
    ),
    "remitly": (
        "https://remitly.com/"
        "?ref=bridge_bot&utm_source=bridge&utm_medium=telegram"
    ),
}


# ── Click storage ─────────────────────────────────────────

def _load() -> list:
    if os.path.exists(CLICKS_FILE):
        try:
            with open(CLICKS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _append(entry: dict) -> None:
    clicks = _load()
    clicks.append(entry)
    with open(CLICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(clicks, f, indent=2)


# ── Routes ────────────────────────────────────────────────

@app.get("/go/{platform_slug}")
async def track_and_redirect(
    platform_slug: str,
    uid: str  = Query(default=""),    # hashed user id
    amt: str  = Query(default=""),    # amount in KRW
    cur: str  = Query(default=""),    # destination currency
):
    """
    Real click tracker.
    User taps Telegram button → lands here → logged → redirected.
    """
    slug        = platform_slug.lower().strip()
    redirect_to = REDIRECT_URLS.get(slug)

    if not redirect_to:
        logger.warning(f"Unknown platform slug: {slug}")
        return RedirectResponse(url="https://wise.com", status_code=302)

    # Log the real click
    try:
        amount_int = int(amt) if amt.isdigit() else 0
        _append({
            "platform":   slug,
            "uid_hash":   uid,
            "amount_krw": amount_int,
            "currency":   cur,
            "clicked_at": datetime.now().isoformat(),
            "date":       datetime.now().strftime("%Y-%m-%d"),
            "week":       datetime.now().strftime("%Y-W%W"),
            "month":      datetime.now().strftime("%Y-%m"),
        })
        logger.info(f"CLICK | {slug} | {cur} | ₩{amount_int:,} | uid={uid[:8]}…")
    except Exception as e:
        logger.error(f"Click log error: {e}")

    return RedirectResponse(url=redirect_to, status_code=302)


@app.get("/stats", response_class=HTMLResponse)
async def stats_dashboard(secret: str = Query(default="")):
    """
    Human-readable click dashboard.
    Protect it: add STATS_SECRET to env vars and visit /stats?secret=yourvalue
    """
    expected = os.getenv("STATS_SECRET", "")
    if expected and secret != expected:
        return HTMLResponse("<h2>401 — pass ?secret=… to view stats</h2>", status_code=401)

    clicks    = _load()
    total     = len(clicks)
    total_krw = sum(c.get("amount_krw", 0) for c in clicks)

    by_platform: dict = {}
    by_date:     dict = {}
    by_currency: dict = {}
    by_month:    dict = {}

    for c in clicks:
        p = c.get("platform", "?")
        d = c.get("date",     "?")
        r = c.get("currency", "?")
        m = c.get("month",    "?")
        by_platform[p] = by_platform.get(p, 0) + 1
        by_date[d]     = by_date.get(d, 0) + 1
        by_currency[r] = by_currency.get(r, 0) + 1
        by_month[m]    = by_month.get(m, 0) + 1

    # Sort & limit
    top_platforms = sorted(by_platform.items(), key=lambda x: -x[1])
    recent_days   = sorted(by_date.items(), reverse=True)[:30]
    months        = sorted(by_month.items(), reverse=True)

    def table(rows, h1, h2):
        html = f"<table border=1 cellpadding=6><tr><th>{h1}</th><th>{h2}</th></tr>"
        for k, v in rows:
            html += f"<tr><td>{k}</td><td>{v}</td></tr>"
        return html + "</table>"

    html = f"""
    <html><head>
    <title>Bridge Tracker Stats</title>
    <style>body{{font-family:monospace;padding:30px;background:#f8f8f8}}
    table{{border-collapse:collapse;margin-bottom:24px}}
    h2{{color:#2563eb}}h3{{margin-top:28px}}</style>
    </head><body>
    <h2>🌉 Bridge Click Tracker</h2>
    <p>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <h3>Summary</h3>
    <b>Total real clicks:</b> {total}<br>
    <b>Total KRW volume tracked:</b> ₩{total_krw:,}<br>

    <h3>By Platform</h3>
    {table(top_platforms, 'Platform', 'Clicks')}

    <h3>By Destination Currency</h3>
    {table(sorted(by_currency.items(), key=lambda x: -x[1]), 'Currency', 'Clicks')}

    <h3>By Month</h3>
    {table(months, 'Month', 'Clicks')}

    <h3>Last 30 Days</h3>
    {table(recent_days, 'Date', 'Clicks')}

    </body></html>
    """
    return HTMLResponse(html)


@app.get("/stats.json")
async def stats_json(secret: str = Query(default="")):
    """JSON version of stats — useful for scripts / admin bot command."""
    expected = os.getenv("STATS_SECRET", "")
    if expected and secret != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    clicks    = _load()
    total_krw = sum(c.get("amount_krw", 0) for c in clicks)

    by_platform: dict = {}
    by_date:     dict = {}
    by_currency: dict = {}

    for c in clicks:
        p = c.get("platform", "?")
        d = c.get("date",     "?")
        r = c.get("currency", "?")
        by_platform[p] = by_platform.get(p, 0) + 1
        by_date[d]     = by_date.get(d, 0) + 1
        by_currency[r] = by_currency.get(r, 0) + 1

    return {
        "total_clicks":     len(clicks),
        "total_krw_volume": total_krw,
        "by_platform":      dict(sorted(by_platform.items(), key=lambda x: -x[1])),
        "by_currency":      dict(sorted(by_currency.items(), key=lambda x: -x[1])),
        "by_date":          dict(sorted(by_date.items(), reverse=True)[:30]),
    }


@app.get("/health")
async def health():
    return {"status": "ok", "clicks": len(_load())}
