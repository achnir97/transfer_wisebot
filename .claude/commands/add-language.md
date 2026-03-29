# Add New Language Support

Walk through adding a new language to the bot. Ask the user for the language details, then make all required changes across both the Telegram bot and the platform-agnostic handler.

## Steps

1. **Get language info from user**
   - Language name in English (e.g., "Burmese")
   - Language name in native script (e.g., "မြန်မာဘာသာ")
   - ISO code (e.g., "my")
   - Home currency code (e.g., "MMK")
   - Key translated strings needed (greeting, help text, button labels)

2. **Add language to `handler_core.py`**
   - Add to the `LANGUAGES` dict with ISO code as key
   - Add translated strings for: welcome message, rate comparison labels, button text, error messages, alert prompts
   - Add the currency to supported currencies if not already present

3. **Update language picker in `bot.py`**
   - Add the new language as an `InlineKeyboardButton` in the language selection menu
   - The picker uses numbered options — add next available number
   - Update `CHOOSING_LANGUAGE` handler callback to recognize the new language code

4. **Update language picker in `whatsapp.py` and `messenger.py`**
   - Both platforms show their own language picker UI
   - Add the new language option in the same numbered format

5. **Add currency pair to `fetchers.py` if new currency**
   - If the home currency isn't already supported (e.g., MMK → KRW), add the pair
   - Check GME and Hanpass APIs support this currency pair

6. **Update `users.py` if needed**
   - If there's a language validation list, add the new ISO code

7. **Test**
   - Run `python -m py_compile bot.py handler_core.py whatsapp.py messenger.py`
   - Start bot locally, run `/start`, verify new language appears in picker
   - Select the new language, verify rate comparison shows in that language
