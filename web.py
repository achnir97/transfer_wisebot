"""
web.py — Bridge unified webhook server
========================================
Runs alongside bot.py on Railway.

Routes:
  GET  /health                    → health check
  GET  /whatsapp/webhook          → Meta webhook verification
  POST /whatsapp/webhook          → incoming WhatsApp messages
  GET  /messenger/webhook         → Meta webhook verification
  POST /messenger/webhook         → incoming Messenger messages
  GET  /go/{platform}             → click tracker redirect (from tracker.py)
  GET  /stats                     → click dashboard

Deploy on Railway as a Web Service:
  Start command: uvicorn web:app --host 0.0.0.0 --port $PORT
  
The Telegram bot (bot.py) stays as a Worker service on Railway.
Both services share the same Supabase database and environment variables.
"""

import logging
import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi import Query

# Import routers from individual platform modules
from whatsapp import router as whatsapp_router
from messenger import router as messenger_router

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bridge Bot — Webhook Server", docs_url=None, redoc_url=None)

# Mount platform routers
app.include_router(whatsapp_router)
app.include_router(messenger_router)


# ── Health check ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "bridge-webhooks",
        "timestamp": datetime.now().isoformat(),
        "platforms": ["whatsapp", "messenger"],
    }


# ── Click tracker (merged from tracker.py) ───────────────

import json

CLICKS_FILE = "real_clicks.json"

REDIRECT_URLS = {
    "gme":     "https://online.gmeremit.com/?utm_source=bridge_bot",
    "hanpass": "https://www.hanpass.com/?utm_source=bridge_bot",
}

def _load_clicks() -> list:
    if os.path.exists(CLICKS_FILE):
        try:
            with open(CLICKS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _append_click(entry: dict) -> None:
    clicks = _load_clicks()
    clicks.append(entry)
    with open(CLICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(clicks, f, indent=2)


@app.get("/go/{platform_slug}")
async def track_and_redirect(
    platform_slug: str,
    uid: str = Query(default=""),
    amt: str = Query(default=""),
    cur: str = Query(default=""),
    src: str = Query(default=""),   # source platform: wa, msg, tg
):
    """Real click tracker — log then redirect to affiliate URL."""
    slug        = platform_slug.lower().strip()
    redirect_to = REDIRECT_URLS.get(slug, "https://online.gmeremit.com")

    try:
        amount_int = int(amt) if amt.isdigit() else 0
        _append_click({
            "platform":   slug,
            "uid_hash":   uid,
            "amount_krw": amount_int,
            "currency":   cur,
            "source":     src,   # which messaging platform
            "clicked_at": datetime.now().isoformat(),
            "date":       datetime.now().strftime("%Y-%m-%d"),
            "month":      datetime.now().strftime("%Y-%m"),
        })
        logger.info(f"CLICK | {slug} | {cur} | ₩{amount_int:,} | src={src} | uid={uid[:8]}")
    except Exception as e:
        logger.error(f"Click log error: {e}")

    return RedirectResponse(url=redirect_to, status_code=302)


@app.get("/stats", response_class=HTMLResponse)
async def stats_dashboard(secret: str = Query(default="")):
    expected = os.getenv("STATS_SECRET", "")
    if expected and secret != expected:
        return HTMLResponse("<h2>401 — pass ?secret=… to view stats</h2>", status_code=401)

    clicks    = _load_clicks()
    total     = len(clicks)
    total_krw = sum(c.get("amount_krw", 0) for c in clicks)

    by_platform: dict = {}
    by_source:   dict = {}
    by_date:     dict = {}
    by_month:    dict = {}

    for c in clicks:
        p  = c.get("platform", "?")
        s  = c.get("source", "unknown")
        d  = c.get("date", "?")
        m  = c.get("month", "?")
        by_platform[p] = by_platform.get(p, 0) + 1
        by_source[s]   = by_source.get(s, 0) + 1
        by_date[d]     = by_date.get(d, 0) + 1
        by_month[m]    = by_month.get(m, 0) + 1

    def tbl(rows, h1, h2):
        html = f"<table border=1 cellpadding=6><tr><th>{h1}</th><th>{h2}</th></tr>"
        for k, v in rows:
            html += f"<tr><td>{k}</td><td>{v}</td></tr>"
        return html + "</table>"

    return HTMLResponse(f"""
    <html><head><title>Bridge Stats</title>
    <style>body{{font-family:monospace;padding:30px;background:#f8f8f8}}
    table{{border-collapse:collapse;margin-bottom:24px}}
    h2{{color:#1B6FEB}}</style></head><body>
    <h2>🌉 Bridge Click Stats</h2>
    <p>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    <b>Total clicks:</b> {total} &nbsp;|&nbsp;
    <b>Total volume:</b> ₩{total_krw:,}<br><br>

    <h3>By Platform (which remittance service)</h3>
    {tbl(sorted(by_platform.items(), key=lambda x: -x[1]), 'Platform', 'Clicks')}

    <h3>By Source (which messaging app)</h3>
    {tbl(sorted(by_source.items(), key=lambda x: -x[1]), 'Source', 'Clicks')}

    <h3>By Month</h3>
    {tbl(sorted(by_month.items(), reverse=True), 'Month', 'Clicks')}

    <h3>Last 30 Days</h3>
    {tbl(sorted(by_date.items(), reverse=True)[:30], 'Date', 'Clicks')}
    </body></html>
    """)


@app.get("/stats.json")
async def stats_json(secret: str = Query(default="")):
    expected = os.getenv("STATS_SECRET", "")
    if expected and secret != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    clicks    = _load_clicks()
    by_platform: dict = {}
    by_source:   dict = {}
    by_date:     dict = {}

    for c in clicks:
        p = c.get("platform", "?")
        s = c.get("source", "unknown")
        d = c.get("date", "?")
        by_platform[p] = by_platform.get(p, 0) + 1
        by_source[s]   = by_source.get(s, 0) + 1
        by_date[d]     = by_date.get(d, 0) + 1

    return {
        "total_clicks":     len(clicks),
        "total_krw_volume": sum(c.get("amount_krw", 0) for c in clicks),
        "by_platform":      dict(sorted(by_platform.items(), key=lambda x: -x[1])),
        "by_source":        dict(sorted(by_source.items(), key=lambda x: -x[1])),
        "by_date":          dict(sorted(by_date.items(), reverse=True)[:30]),
    }