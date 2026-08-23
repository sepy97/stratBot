# stratBot

An algorithmic trading bot built on the **STRAT methodology** — a candle-classification system that categorizes each candle relative to the prior candle. The system supports both live trading (via Alpaca) and historical backtesting.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Running the Live Bot](#running-the-live-bot)
- [CLI Control](#cli-control)
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
├── Main.py                  # Live trading entry point (multi-day continuous loop)
├── stratbot                 # CLI control utility (start/stop/kill/status/pause/resume)
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

The bot runs continuously across multiple trading days. It trades during market hours and sleeps overnight, waking up 20 minutes before the next market open to refresh candle data.

### Start

```bash
./stratbot start            # Background the bot
./stratbot start --fresh    # Ignore saved state, start clean
python Main.py              # Or run in foreground (for tmux/systemd)
```

On startup the bot will:

1. Load the watchlist from `Watchlists/NASDAQ100_2025.csv`
2. Fetch historical bars per timeframe (m5, m15, m30, m60, d, w, m, q) for each symbol
3. Resume open trades from `~/.stratbot/session_state.json` if a previous session was saved
4. Start one `Ticker` thread per symbol plus `DataRetrieval` and `Broker` threads
5. Poll Alpaca for latest bars every 5 seconds via APScheduler
6. Trade during market hours, sleep overnight, repeat

**Strategies active by default:** `BasicDailyAS` and `StratLab2dGM` across all NASDAQ 100 symbols.

> **Note:** `Broker.py` currently only logs intended orders — actual Alpaca order placement is not yet implemented.

### Stop and Resume

```bash
./stratbot stop             # Graceful exit: save state, positions stay open at broker
```

The bot saves all active trades to `~/.stratbot/session_state.json`. On next startup, it automatically loads the saved state, reconciles with the broker, fetches fresh candles, and continues trading.

### Kill Switch

```bash
./stratbot kill             # Force-close ALL positions, delete state, clean slate
```

This force-closes every open position at the last known price, deletes the session state, and exits. Use this when you want to stop trading entirely.

---

## CLI Control

The `stratbot` CLI controls the running bot via Unix signals and file flags.

```bash
./stratbot start [--fresh]   # Start bot in background (--fresh ignores saved state)
./stratbot stop              # Graceful exit — save state, keep positions at broker
./stratbot kill              # Force-close all positions and exit
./stratbot status            # Show open positions, P&L, uptime, market status
./stratbot pause             # Stop new entries, keep managing open trades
./stratbot resume            # Resume new entries after pause
./stratbot logs [-f] [-n N]  # Tail the bot's log (--file app|trades|events|out, --ticker SYM)
```

`status` exits with `0` when the bot is running, `1` when it is not, and `2` when it is running but `status.json` is more than 15 s old — so it can be used as a health check from scripts, cron, or systemd.

### How It Works

| Command | Mechanism |
|---------|-----------|
| `start` | Checks `alpaca_config.py` exists and `venv/bin/python` is ≥3.12, spawns `Main.py` in background with output to `~/.stratbot/stratbot.out`, then waits for `~/.stratbot/run.pid` (or reports the crash with the last lines of output) |
| `stop` | Sends SIGTERM to bot process; bot saves state and exits gracefully |
| `kill` | Sends SIGUSR1 to bot process; bot force-closes all positions and exits |
| `status` | Reads `~/.stratbot/status.json` (updated every 5s by the bot) |
| `pause` | Creates `~/.stratbot/pause.flag`; bot skips new entries but keeps managing open trades |
| `resume` | Removes the pause flag file |
| `logs` | Tails a file from the bot's log directory (taken from `status.json` while running, otherwise derived from `config.toml`; falls back to the most recent archived run). `--file out` shows the process stdout/stderr captured by `start` |

### Status Output

```
  State     : running
  Uptime    : 2h 47m
  Market    : OPEN
  Last tick : 2026-08-21 12:17:05  (3s ago)
  Last flip : m15 @ 2026-08-21 12:15:00  (2m 05s ago)
  Next open : 2026-08-24 09:30:00  (in 2d 21h)
  Tickers   : 98
  Open      : 3 trade(s)
  Closed    : 12 today
  P&L       : $245.67

  Open positions:
    AAPL    LONG   entry $150.25  day 1  BasicDailyAS
    MSFT    SHORT  entry $380.00  day 0  BasicDailyAS
    NVDA    LONG   entry $820.50  day 2  StratLab2dGM
  Logs      : /path/to/logs/<user>/current
```

### Startup Flags

```bash
python Main.py              # Auto-resumes if session_state.json exists
python Main.py --fresh      # Ignores saved state, starts clean
python Main.py --terminate  # Closes all saved positions and exits (without running the bot)
```

### Runtime Files

```
~/.stratbot/
├── run.pid              # Bot process ID (deleted on clean exit)
├── stratbot.out         # stdout/stderr of Main.py when launched via `stratbot start` (appended per start)
├── status.json          # Live status (updated every 5s by the bot)
├── pause.flag           # Exists = paused (no new entries, open trades managed)
└── session_state.json   # Active trades snapshot (written on graceful stop + every 5min)
```

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

### Log Files

All logs are written to `<icloud_logs_dir>/<username>/current/` during a session.
At startup, any leftover logs from a previous crashed session are automatically
archived to `<username>/<YYYY-MM-DD>/<HH.MM.SS>/`. At shutdown, the current
session's logs are archived the same way.

| File | Contents | When to read it |
|------|----------|-----------------|
| `app.log` | All operational activity (INFO+), errors, warnings. Ticker debug noise is suppressed; ledger JSON is excluded. | **"What happened this session?"** — start here for any investigation. |
| `trades.log` | Trade entries, exits, forced closes, and the session P&L summary. One line per action. | **"Show me today's trades."** — quick scan of all trade activity. |
| `events.jsonl` | Structured JSON-lines audit trail. Every significant event (entry, exit, stop update, signal, session start/end) with a monotonic `seq` number. | **"Analyze P&L programmatically."** — parse with `jq`, pandas, or any JSON tool. |
| `tickers/strat_<SYM>.log` | Per-symbol detail at DEBUG level: candle creation, bar updates, timeframe flips, signals. | **"Why did AAPL exit early?"** — deep-dive into one symbol's full timeline. |
| (console) | Filtered live view: trade events, system messages, errors. No per-bar noise. | **During live trading** — monitor in real time. |

### Reading the Logs

**Quick P&L check:**
```bash
grep "EXIT\|ENTRY" trades.log
```

**Structured analysis with jq:**
```bash
# All exits with gain percentage
jq 'select(.event=="exit")' events.jsonl

# Losers only
jq 'select(.event=="exit" and .gain_pct < 0)' events.jsonl

# Everything for one symbol
jq 'select(.symbol=="AAPL")' events.jsonl
```

**Debug a specific symbol:**
```bash
cat tickers/strat_AAPL.log
```

**Find errors across the session:**
```bash
grep "ERROR\|CRITICAL" app.log
```

**Filter app.log by domain** (logger name is in the format string):
```bash
grep "| broker |" app.log      # broker activity
grep "| market |" app.log      # market data events
grep "| system |" app.log      # system init/status
```

### events.jsonl Format

Each line is a self-contained JSON object:
```json
{"seq": 1, "ts": "2026-03-27T09:31:00", "event": "session_start", "mode": "live"}
{"seq": 2, "ts": "2026-03-27T10:15:23", "event": "entry", "symbol": "AAPL", "strategy": "BasicDailyAS", "direction": "LONG", "triggerPrice": 150.00, "stop": 148.50, "RR": 2.1}
{"seq": 3, "ts": "2026-03-27T10:45:10", "event": "stop_update", "symbol": "AAPL"}
{"seq": 4, "ts": "2026-03-27T14:30:00", "event": "exit", "symbol": "AAPL", "strategy": "BasicDailyAS", "direction": "LONG", "exitPrice": 153.00, "stopType": "trailing", "gain_pct": 2.0}
{"seq": 5, "ts": "2026-03-27T16:00:00", "event": "session_end", "mode": "graceful"}
```

| Field | Description |
|-------|-------------|
| `seq` | Monotonic sequence number (assigned by the logging process; guaranteed unique per session) |
| `ts` | ISO 8601 timestamp of when the event was emitted |
| `event` | Event type: `session_start`, `session_end`, `entry`, `exit`, `signal`, `stop_update`, `forced_close`, `bt_entry`, `bt_exit`, `bt_session_end` |
| Other fields | Vary by event type: `symbol`, `strategy`, `direction`, `price`, `gain_pct`, etc. |

### Log Archival

Logs are archived automatically:
- **At startup**: any leftover `current/` directory (from a crash) is moved to `<YYYY-MM-DD>/<HH.MM.SS>/`
- **At shutdown**: the completed session's `current/` is moved the same way

Archives live in the iCloud logs directory configured in `config.toml`:
```
<logs_path>/<username>/
  ├── current/           ← active session (wiped on archive)
  ├── 2026-03-27/
  │   ├── 09.30.15/      ← morning session
  │   └── 14.00.22/      ← afternoon session
  └── 2026-03-28/
      └── 09.31.00/
```

### Trade CSVs

All trade records (both live and backtest) are written to the `Trades/` directory with timestamped filenames.

---

## Architecture

The architecture diagrams are included inline below.

### Live Trading

```
User ──► stratbot CLI ──signals/flags──► Main.py (the bot)
                                            │
                                 ┌──────────┴──────────┐
                                 │   APScheduler (5s)   │
                                 │         │            │
                                 │   DataRetrieval      │
                                 │         │            │
                                 │   Ticker (×N)        │
                                 │         │            │
                                 │      Broker          │
                                 └──────────┬──────────┘
                                            │
                            ┌───────────────┼───────────────┐
                            ▼               ▼               ▼
                       Alpaca API    ~/.stratbot/       Log Files
                     (data+orders)  (state+status)   (app/trades/jsonl)
```

- The bot runs continuously: trades during market hours, sleeps overnight
- `stratbot` CLI sends signals (SIGTERM/SIGUSR1) and manages file flags for control
- State is checkpointed to `~/.stratbot/session_state.json` every 5 minutes and on graceful exit
- On resume, saved trades are reconstructed and reconciled with the broker

### Backtesting

```
BackTester.py
    │
    ├── mp.Pool (parallel per symbol)
    │       │
    │       ├── backtest_symbol() ──► enterTrade() / updateTrade()
    │       │
    │       └── alpaca_chart.DataRetrieval ──► ChartDB (SQLite cache)
    │
    └── Trades/*.csv (results)
```

---

## Important Notes

- **Broker stub**: `Broker.py` logs all intended orders but does **not** place real orders with Alpaca yet. Live trading is paper-log only until this is implemented.
- **Python ≥ 3.12**: The codebase uses structural pattern matching (`match`/`case`) introduced in Python 3.10+.
- **SQLite cache**: Historical candle data fetched during backtesting is cached locally via `ChartDB`. Subsequent backtests on the same date range are significantly faster.
- **Rate limiting**: `alpaca_chart.py` enforces a shared 200 requests/min limit across all backtest worker processes via `multiprocessing.Manager`.
- **Candle window (live)**: Each `Ticker` maintains exactly 3 candles per timeframe — sufficient for all 3-candle combo pattern detection.
- **Legacy files**: `bot.py`, `config.py`, and `session.py` are from an earlier TD Ameritrade prototype and are not wired into the current live or backtest pipelines.
