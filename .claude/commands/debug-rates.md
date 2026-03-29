# Debug Rate Fetching

Diagnose why rates are missing, stale, or incorrect. Run through each layer systematically.

## Step 1 — Check Cache
Read `rate_cache.json`:
- Is it present and non-empty?
- What is the `cached_at` timestamp? Is it within the 30-minute TTL?
- Which currencies/providers are cached?
- Are any providers missing or showing `null`?

## Step 2 — Test Fetchers Directly
Run a quick async test to call each provider API directly:
```python
import asyncio, httpx
# Test GME and Hanpass fetch functions from fetchers.py
```
Check:
- HTTP status codes
- Response structure matches what the parser expects
- Any rate limiting or IP blocks (check for 403/429 responses)
- Timeout issues (default is 10s)

## Step 3 — Check rates.py Aggregator
Read `rates.py`:
- Verify the cache TTL constant
- Check the `get_all_rates()` function logic
- Confirm both providers are included in the return value
- Look for any silent exception swallowing

## Step 4 — Check handler_core.py Display
Read how `handler_core.py` formats and displays rates:
- Is it handling `None` values gracefully?
- Are currency codes matching what the fetchers return?

## Step 5 — Check Logs
```bash
tail -100 bridge_bot.log | grep -i "rate\|fetch\|error\|exception"
```
Look for recent errors in rate fetching.

## Step 6 — Report
Summarize:
- Root cause identified
- Which layer is failing (network, parser, cache, display)
- Recommended fix
