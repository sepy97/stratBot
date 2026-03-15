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

- **Cache initial candle data to speed up startup**
  On each startup, `get_initial_data()` fetches the last 4 bars per timeframe per symbol from Alpaca,
  which is a large number of API calls for a big watchlist. Pre-fetch and persist this data to a local
  SQLite cache (or reuse `ChartDB`) at market open via cron, so the bot can seed candle windows
  instantly from disk instead of hitting the API on every restart during the trading day.

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

## Testing

- **`candles.py` — unit test candle classification**
  For every combination of kind (1/2/3), subtype (U/D/none), direction (G/R), and pattern (H/S/X),
  assert that `get_kind()`, `get_subtype()`, `get_direction()`, `get_pattern()`, and `to_string()`
  return the expected values. Edge cases: exact high/low equality (inside candle boundary),
  outside candle with both sides broken simultaneously.

- **`BackTestStrategy.py` — unit test each strategy's entry signal**
  For each strategy, construct minimal `chartDictNew` / `chartDictOld` dicts with synthetic
  `Candle` objects and assert that `getNewTrade()` returns the correct trigger price and direction
  (or no trade) for both the positive and negative cases.

- **`BackTestStrategy.py` — unit test stop progression**
  Given a sequence of daily candles, verify that `getStop()` produces:
  - day 0: correct 50%-range or entry-candle-low stop
  - day 1: breakeven (entry price)
  - day 2+: trailing prior-candle low/high

- **`BackTester.py` — regression test with fixed AAPL data**
  `AAPL_daily.csv` is already in the repo. Run a backtest on a known date range with a fixed strategy
  and assert the output CSV matches a golden reference (symbol count, trade count, total gain).
  This catches regressions in `enterTrade()` / `updateTrade()` logic without hitting the Alpaca API.

- **`MarketTimeManager.py` — unit test timeframe flip detection**
  Mock `datetime.now()` and assert `detectTFFlip()` correctly identifies transitions at
  known boundary times for m5, m15, m30, m60, d, w, m, and q, including across DST boundaries.

- **`alpaca_chart.py` — mock Alpaca API responses in tests**
  Wrap `StockHistoricalDataClient` behind a thin interface so tests can inject pre-recorded
  bar responses (e.g. from the existing CSV files) without making live network calls.
  Validate candle assembly logic for edge cases: partial last candle, gap day, early close.

- **`earnings_calendar.py` — unit test earnings date lookup**
  Given a small CSV fixture, assert `get_ER_by_ticker()` returns the correct pre-earnings
  trading day for BMO and AMC entries, and returns an empty list for unknown tickers.

---

## Future Plans

### Cloud Deployment

- **Containerize the bot**
  Write a `Dockerfile`. The bot is a long-running process, not a web service, so
  this is straightforward. Pin the Python version and copy in `requirements.txt`.

- **Deploy to a cloud host**
  Cheapest options for a single long-running process:
  - Small VPS (DigitalOcean ~$6/mo, Hetzner ~$4/mo) with Docker + systemd
  - Railway / Render — push-to-deploy, ~$5-7/mo
  - AWS ECS Fargate or GCP Cloud Run Jobs — more complex, auto-restarts

- **Process supervisor / auto-restart**
  Wrap the bot in systemd or supervisord so it recovers from crashes automatically.
  Individual thread crashes should attempt restart instead of killing the whole bot.

- **Scheduled start/stop**
  Use cron or a cloud scheduler to start the bot before market open and stop it after
  close — saves resources on nights, weekends, and holidays.

- **Persistent storage for trade history**
  Mount a volume or use a lightweight DB (SQLite file on disk, or free-tier Postgres)
  for trade history and state recovery after restarts. The JSONL event ledger could
  also live here instead of flat files.

### Notifications & Monitoring

- **Telegram bot for trade alerts**
  Add a `notify()` function using the Telegram Bot API (free, instant, no infrastructure).
  Post on: trade entry/exit, session start/end, errors, and daily PnL summaries.

- **Trade dashboard / visibility**
  Expose a lightweight web endpoint (FastAPI) or write session data to a shared location
  for viewing open positions, PnL, and trade history. Could also be a simple Telegram
  `/status` command instead of a full web app.

- **Handle internet connectivity loss**
  Add retry/reconnect logic in `DataRetrieval` for network errors so the bot
  can recover without requiring a manual restart.

### Control Plane

- **Kill switch**
  Options (not mutually exclusive):
  - Telegram bot command (`/kill`, `/pause`, `/resume`) that sets a `threading.Event`
  - HTTP endpoint (`POST /kill`) behind auth
  - File-based flag (touch a sentinel file to trigger shutdown)

- **Remote controls**
  Extend the Telegram bot or HTTP API with commands:
  - `/status` — open positions, current PnL, bot health
  - `/pause` — stop new entries but keep managing open trades
  - `/resume` — re-enable entries
  - `/watchlist add/remove SYMBOL` — dynamic watchlist management

### Risk Management & Sizing

- **Position sizing**
  Everything currently defaults to `quantity=1`. Add account-aware sizing —
  fixed dollar amount per trade or percentage of equity.

- **Portfolio-level risk limits**
  Max daily loss limit, max concurrent positions, max position size per symbol,
  total portfolio exposure cap.

### Market Hours & Scheduling

- **Replace `time.sleep(6*60*60)` with market-calendar-aware lifecycle**
  `MarketTimeManager` already has open/close times. Use those to auto-start at open
  and shut down at close, handling early-close days correctly.

### Cleanup

- **Remove legacy modules**
  `session.py` (TD Ameritrade), `bot.py` (old entry point), and the data-fetching
  functions in `config.py` are unused. Remove them and drop `td-ameritrade-python-api`
  from `requirements.txt`.

