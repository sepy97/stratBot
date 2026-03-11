# stratBot

An algorithmic trading bot built on the **STRAT methodology** — a candle-classification system that categorizes each candle relative to the prior candle. The system supports both live trading (via Alpaca) and historical backtesting.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Running the Live Bot](#running-the-live-bot)
- [Running the Backtester](#running-the-backtester)
- [Strategies](#strategies)
- [Configuration](#configuration)
- [Output](#output)
- [Architecture](#architecture)
- [Important Notes](#important-notes)

---

## How It Works

### Candle Classification (The STRAT)

Every candle is classified relative to the previous candle into one of three kinds:

| Kind | Meaning |
|------|---------|
| `1`  | **Inside** — high ≤ prev high AND low ≥ prev low |
| `2`  | **Directional** — breaks one side only (`U` = up, `D` = down) |
| `3`  | **Outside** — engulfs the previous candle (new high AND new low) |

Each candle also has:
- **Direction**: `G` (green, close ≥ open) or `R` (red)
- **Pattern**: `H` (hammer), `S` (shooter), or `X` (neither)

The full candle string is `kind + subtype + direction + pattern`, e.g. `2UGX` = bullish directional-up green candle with no hammer/shooter pattern.

### Actionable Signals (AS)

A bullish AS is triggered when a candle breaks above the prior candle's high following a setup combo (e.g. `1-2U`, `2D-2U`). The entry trigger is the prior candle's high; the stop is placed below the entry candle's low or a percentage below entry.

### Timeframe Continuity (TFC)

Multiple timeframe alignment is used as a filter: the daily, weekly, and monthly candles must all be showing green (close > open) for the position to be entered. This ensures trades are taken in the direction of the higher timeframe trend.

---

## Project Structure

```
stratBot/
├── Main.py                  # Live trading entry point
├── BackTester.py            # Backtesting engine entry point
├── BackTestStrategy.py      # Core strategy logic (shared by live + backtest)
├── strategy.py              # Live trading wrapper around BackTestStrategy
├── Ticker.py                # Per-symbol thread managing candle state (live)
├── Trade.py                 # Trade object for live trading
├── Broker.py                # Order execution thread (Alpaca integration stub)
├── DataRetrieval.py         # Live market data thread (Alpaca)
├── alpaca_chart.py          # Historical data fetcher with SQLite caching (backtest)
├── chartDB.py               # SQLite candle cache
├── candles.py               # Candle dataclass and classification logic
├── patterns.py              # Standalone 2-1-2 pattern functions
├── MarketTimeManager.py     # Market calendar, TF flip detection, timestamps
├── earnings_calendar.py     # Earnings calendar (force-close before earnings)
├── log_functions.py         # Centralized cross-process logging setup
├── alpaca_config.py         # Alpaca API credentials
├── config.toml              # Strategy and path configuration
├── config.py                # Legacy data export utilities (not in main pipeline)
├── session.py               # Legacy TD Ameritrade session (not in main pipeline)
├── util.py                  # Shared enums and helper functions
├── Watchlists/
│   └── NASDAQ100_2025.csv   # Symbols to trade/backtest
├── Trades/                  # Backtest and live trade output CSVs
└── requirements.txt
```

---

## Setup

### Requirements

- Python ≥ 3.12 (the code uses `match` statements)
- An [Alpaca](https://alpaca.markets/) account with paper or live API keys

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure API Keys

Open `alpaca_config.py` and replace the placeholder credentials with your own:

```python
alpaca_config = {
    "key": "YOUR_ALPACA_API_KEY",
    "secret_key": "YOUR_ALPACA_SECRET_KEY"
}
```

> **Security**: Never commit real API keys to version control. Consider loading them from environment variables instead:
> ```python
> import os
> alpaca_config = {
>     "key": os.environ["ALPACA_KEY"],
>     "secret_key": os.environ["ALPACA_SECRET"]
> }
> ```

---

## Running the Live Bot

```bash
python Main.py
```

The bot will:

1. Load the watchlist from `Watchlists/NASDAQ100_2025.csv`
2. Fetch the last 4 historical bars per timeframe (m5, m15, m30, m60, d, w, m, q) for each symbol to seed the candle windows
3. Start one `Ticker` thread per symbol plus `DataRetrieval` and `Broker` threads
4. Poll Alpaca for the latest bars every 5 seconds via APScheduler
5. Detect timeframe candle flips and pass fresh candles to each `Ticker`
6. Evaluate strategy signals and enter/exit trades via the `Broker` queue
7. Shut down gracefully after 6 hours, force-closing any remaining open positions
8. Write a session summary (win rate, total gain, per-strategy stats) to `trades.log`

**Strategies active by default:** `BasicDailyAS` and `StratLab2dGM` across all NASDAQ 100 symbols.

> **Note:** `Broker.py` currently only logs intended orders — actual Alpaca order placement is not yet implemented.

---

## Running the Backtester

Edit the configuration block at the bottom of `BackTester.py`:

```python
if __name__ == '__main__':
    startDay_str    = "2023-01-01 0:30:00"
    endDay_str      = "2025-12-20 23:30:00"
    watchlist_name  = 'NASDAQ100_2025'       # file in Watchlists/
    strategy_name   = "StratLab2dGM"
    earnings_file   = '/path/to/EarningsCalendar_2025-12-21.csv'
```

Then run:

```bash
python BackTester.py
```

### What the Backtester Does

1. Fetches full daily + higher-timeframe (weekly, monthly, quarterly) chart data from Alpaca for all symbols in the watchlist (results are cached in SQLite via `chartDB.py`)
2. Parallelizes per-symbol backtesting using `multiprocessing.Pool`
3. For each trading day, evaluates the strategy signal on daily + HTF candle data
4. When a signal is triggered, pulls 1-minute intraday data to pinpoint the precise entry and exit timestamps
5. Tracks stop adjustments: day 0 = entry candle low; day 1 = breakeven; day 2+ = trailing prior candle low/high
6. Forces trade closure before earnings (if an earnings calendar CSV is provided)
7. Writes results to `Trades/trades_<start>_<end>_<watchlist>_<strategy>_<timestamp>.csv`

### Backtest Output CSV Columns

| Column | Description |
|--------|-------------|
| `symbol` | Ticker symbol |
| `direction` | `LONG` or `SHORT` |
| `entryPrice` | Fill price at entry |
| `entryTimestamp` | Entry datetime |
| `exitPrice` | Fill price at exit |
| `exitTimestamp` | Exit datetime |
| `gain%` | Percentage gain/loss |
| `daysOpen` | Number of trading days held |
| `exit_comment` | Reason for exit (stop, target, earnings, etc.) |
| `stop` | Final stop price |
| `d_combo`, `w_combo`, `m_combo`, `q_combo` | 3-candle combo string at entry per TF |
| `d_tfc`, `w_tfc`, `m_tfc`, `q_tfc` | TFC (trend) flag per timeframe at entry |

---

## Strategies

All strategies are implemented in `BackTestStrategy.py` and inherited by `strategy.py` for live use.

| Strategy | Description |
|----------|-------------|
| `BasicDailyAS` | Pure daily actionable signal: `1-2U` or `2D-2U` (or `3`) combo, no HTF filter |
| `SimpleDailyAS` | Daily AS + D/W/M TFC filter (all three timeframes must be green) |
| `SimpleAS_DailyTFCStop` | `SimpleDailyAS` + stop placed at TFC flip level on day 0 |
| `SimpleAS_DailyTFCOrPCTStop` | `SimpleDailyAS` + tighter of TFC stop or 1% fixed stop |
| `LTFEntryOnHTFSignal` | Daily AS while W/M/Q are also showing AS; D/W/M TFC green |
| `LTFEntryOnHTFSignal_V2` | V1 + rejects opposing HTF actionable signal against position |
| `HammerShooterInsideDayAS` | Daily AS on hammer/shooter or inside day pattern, no TFC filter |
| `HammerShooterInsideDayAS_WithGaps` | Same but allows gap-over/gap-under trigger |
| `DailyTrigAndTarget` | Daily AS with explicit target = prior candle high/low |
| `StratLab2dGM` | Bullish daily AS + 2-down monthly candle + green monthly candle at entry |

### Stop Progression (most strategies)

| Day Open | Stop Placement |
|----------|---------------|
| 0 (entry day) | 50% of entry candle range or entry candle low |
| 1 | Moved to breakeven (entry price) |
| 2+ | Trailing: prior candle low (long) / prior candle high (short) |

---

## Configuration

### `config.toml`

```toml
[paths]
log_destination = "/path/to/logs/"   # Where to archive log files

[strategy]
# Weighted strategy settings (partial implementation)
```

### `alpaca_config.py`

Holds the Alpaca API key and secret. Used by `Main.py`, `MarketTimeManager.py`, and `alpaca_chart.py`.

### Watchlists

Plain CSV files in `Watchlists/` — one ticker symbol per line, no header.

```
AAPL
MSFT
NVDA
...
```

### Earnings Calendar

CSV files with columns `act_symbol`, `date`, `when` (`BMO` = before market open, `AMC` = after market close). Used by the backtester to force-close trades before earnings events. Pre-built files are included:

- `EarningsCalendar_2025-05-18.csv`
- `EarningsCalendar_2025-12-21.csv`

---

## Output

### Log Files (Live Trading)

| File | Contents |
|------|---------|
| `live_trading.log` | Main bot activity, errors, session summary |
| `trades.log` | Trade entry/exit events with prices and gain |
| `strat_<SYMBOL>.log` | Per-ticker strategy evaluation detail |

### Trade CSVs

All trade records (both live and backtest) are written to the `Trades/` directory with timestamped filenames.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐   ┌──────────────────────────────┐
│                      Main.py (live)                          │   │      BackTester.py           │
│                                                              │   │                              │
│  APScheduler (5s)                                            │   │  runBacktest()               │
│       │                                                      │   │       │                      │
│  scheduling() ──► DataRetrieval (Thread)                     │   │  mp.Pool                     │
│                        │                                     │   │       │                      │
│              ticker_queues[symbol]                           │   │  backtest_symbol() (per sym) │
│                        │                                     │   │       │                      │
│          ┌─────────────┼─────────────┐                       │   │  enterTrade() / updateTrade()│
│          ▼             ▼             ▼                       │   │       │                      │
│   Ticker(AAPL)   Ticker(MSFT)  Ticker(NVDA)  …(one/symbol)  │   │  alpaca_chart.DataRetrieval  │
│   ┌───────────┐  ┌───────────┐ ┌───────────┐               │   │       │                      │
│   │ candles{} │  │ candles{} │ │ candles{} │               │   │  ChartDB (SQLite cache)      │
│   │strategies │  │strategies │ │strategies │               │   └──────────────────────────────┘
│   │  trades[] │  │  trades[] │ │  trades[] │               │
│   └─────┬─────┘  └─────┬─────┘ └─────┬─────┘               │
│         └──────────────┼──────────────┘                      │
│                        │ Trade objects                        │
│                  broker_queue                                 │
│                        │                                     │
│                  Broker (Thread)                              │
│                  [stub — logs only]                           │
└──────────────────────────────────────────────────────────────┘
```

---

## Important Notes

- **Broker stub**: `Broker.py` logs all intended orders but does **not** place real orders with Alpaca yet. Live trading is paper-log only until this is implemented.
- **Python ≥ 3.12**: The codebase uses structural pattern matching (`match`/`case`) introduced in Python 3.10+.
- **SQLite cache**: Historical candle data fetched during backtesting is cached locally via `ChartDB`. Subsequent backtests on the same date range are significantly faster.
- **Rate limiting**: `alpaca_chart.py` enforces a shared 200 requests/min limit across all backtest worker processes via `multiprocessing.Manager`.
- **Candle window (live)**: Each `Ticker` maintains exactly 3 candles per timeframe — sufficient for all 3-candle combo pattern detection.
- **Legacy files**: `bot.py`, `config.py`, and `session.py` are from an earlier TD Ameritrade prototype and are not wired into the current live or backtest pipelines.