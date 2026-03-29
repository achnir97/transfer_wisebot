# Add New Rate Provider

Walk through adding a new remittance provider step by step. Ask the user for the provider name and API details, then make all the required changes.

## Steps

1. **Get provider info from user**
   - Provider name (e.g., "Remitly", "Wise")
   - API endpoint URL and authentication method
   - Response format (what field contains the exchange rate)

2. **Add API client in `fetchers.py`**
   - Create a new `async def fetch_<provider>_rates(session, currency_pair)` function
   - Use `httpx.AsyncClient` with a timeout (default 10s)
   - Match the existing pattern from `fetch_gme_rates` or `fetch_hanpass_rates`
   - Handle errors: return `None` on failure, log the error

3. **Integrate into `rates.py`**
   - Import the new fetcher
   - Add it to the `get_all_rates()` aggregator function
   - Include the provider in the comparison result dict
   - Test the cache invalidation logic still works

4. **Add referral link in `referral.py`**
   - Add the provider's affiliate base URL
   - Add a `generate_<provider>_link(user_id, currency)` function
   - Register the provider in the link-generation router

5. **Update display in `handler_core.py`**
   - Add the provider to the rate comparison message formatter
   - Add a "Send Here" button for the provider
   - Ensure button callback routes to the new referral link

6. **Update `supabase_schema.sql` if needed**
   - If tracking clicks per provider, add the provider name to any enum or reference table

7. **Verify**
   - Run `python -m py_compile fetchers.py rates.py referral.py handler_core.py`
   - Test locally: `python bot.py` and trigger a rate comparison
   - Check the new provider appears in the comparison output
