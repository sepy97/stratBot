# TODO

## Live Bot

- **`Broker.py` — implement actual order placement**
  `Broker.py:33` has a stub comment where Alpaca paper/live orders should be placed.
  Until this is done, the live bot only logs intended trades and never executes them.

- **API key security**
  `alpaca_config.py` has credentials hardcoded in plaintext.
  Move to environment variables or a secrets manager, and add the file to `.gitignore`.

- **Separate initialization from the main loop** (`Main.py:79`)
  The symbol/chart initialization block should run once via cron at market open, not inline at startup.

- **Validate initial data is non-empty** (`Ticker.py:194`)
  `get_initial_data()` result is used without checking for empty/error responses.

- **Invalidate patterns that span shortened trading days**
  Candle combos should not include candles from early-close sessions (day-before-holiday half days).

---

## Market Time / Calendar

- **`MarketTimeManager` methods still use `pandas_market_calendars` directly**
  Several methods (`getPreviousTradingDay`, `getTodayOpenTime`, `getTodayCloseTime`,
  `getOpenCloseAtDay`, `isMarketOpen`, `getCandleChange`, `detectTFFlip`, `getProperStartTime`)
  are marked to be converted to use the Alpaca `TradingClient` calendar endpoint instead.

- **`getProperStartTime` does not verify the result is a trading day** (`MarketTimeManager.py:201`)

- **`getCandleOpenCloseTime` does not bounds-check against the calendar range** (`MarketTimeManager.py:428,446`)

---

## Code Quality

- **Timeframes are bare strings throughout the codebase**
  Replace `"m5"`, `"m15"`, `"d"`, `"w"`, etc. with a proper `Timeframe` enum to avoid typos
  and enable IDE support.

- **`updater.py` is incomplete**
  The class has no description and the scheduler thread-pool size (10 000) is hardcoded.
  Either finish this module or remove it.

- **`log_functions.py` example usage block is stale** (`log_functions.py:166`)
  The example at the bottom of the file pre-dates the current multiprocess logging design
  and needs to be rewritten or removed.

---

## Future / Nice-to-Have

- **Notification / monitoring interface**
  A Telegram bot for trade alerts and session summaries would be more practical
  than a full web app.

- **Deploy to a cloud VM**
  The bot needs to run continuously during market hours.
  A small DigitalOcean Droplet or AWS EC2 instance with a systemd service is sufficient.

- **Handle internet connectivity loss**
  Add retry/reconnect logic in `DataRetrieval` for network errors so the bot
  can recover without requiring a manual restart.

