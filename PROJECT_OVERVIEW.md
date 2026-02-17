# stratBot - Comprehensive Project Overview

## Table of Contents
- [Project Purpose](#project-purpose)
- [Architecture Overview](#architecture-overview)
- [Core Modules](#core-modules)
- [Data Flow & Execution](#data-flow--execution)
- [External Dependencies](#external-dependencies)
- [Key Concepts](#key-concepts)
- [Configuration](#configuration)

---

## Project Purpose

**stratBot** is an **algorithmic trading bot** designed to identify and execute trading opportunities through multi-timeframe technical analysis and pattern recognition. The bot continuously monitors a watchlist of stock tickers, analyzes candlestick patterns across 8 different timeframes (ranging from 5-minute to quarterly charts), and executes trades when strategy-defined conditions are met.

### Primary Capabilities:
- **Real-time market monitoring** via Alpaca API integration
- **Multi-timeframe technical analysis** (5min, 15min, 30min, 60min, daily, weekly, monthly, quarterly)
- **Pattern recognition** using candlestick classification and 2-1-2 reversal patterns
- **Weighted strategy scoring** across timeframes with configurable thresholds
- **Backtesting engine** for historical strategy validation and optimization
- **Paper trading** on Alpaca accounts (live trading stub in place)

### Current Status:
The bot is in active development with a working data retrieval and analysis pipeline. The broker integration is stubbed out and ready for order execution implementation.

---

## Architecture Overview

### System Design
stratBot uses a **multi-threaded architecture** with queue-based inter-thread communication:

```
┌─────────────────────────────────────────────────────────────┐
│                     Main.py (Scheduler)                      │
│  APScheduler: Every 5 seconds, signals data retrieval       │
└────────┬────────────────────────────────────────────────────┘
         │
    ┌────┴─────┬──────────────┬──────────────┐
    ▼          ▼              ▼              ▼
┌───────┐  ┌───────┐      ┌───────┐      ┌────────┐
│ TSLA  │  │ AAPL  │      │  QQQ  │      │  SQQQ  │
│Ticker │  │Ticker │      │Ticker │      │ Ticker │
└───┬───┘  └───┬───┘      └───┬───┘      └───┬────┘
    │          │              │              │
    └──────────┴──────────────┴──────────────┘
                      │
                      ▼
              ┌──────────────┐
              │ Broker Queue │
              └──────┬───────┘
                     ▼
              ┌────────────┐
              │   Broker   │
              │  (Alpaca)  │
              └────────────┘

       ┌──────────────────────┐
       │  DataRetrieval       │
       │  (Alpaca API)        │
       │  Every 5 sec poll    │
       └──────────────────────┘
```

### Threading Model:
1. **Main Thread**: Runs APScheduler, triggers data retrieval every 5 seconds
2. **DataRetrieval Thread**: Fetches latest market data from Alpaca API
3. **Ticker Threads**: One per symbol, analyzes data and generates signals
4. **Broker Thread**: Receives trade signals and executes orders

### Communication:
- **Queues**: Thread-safe data passing between components
- **Conditions**: Thread synchronization (wait/notify pattern)
- **Time Quantization**: 5-second polling intervals aligned to market time

---

## Core Modules

### 1. Main.py - Application Entry Point
**Purpose**: Orchestrates the entire trading bot system

**Key Responsibilities**:
- Initializes global queues and thread conditions for inter-thread communication
- Creates watchlist: `["TSLA", "AAPL", "QQQ", "SQQQ"]` (configurable)
- Spawns threads: DataRetrieval, Broker, and one Ticker per symbol
- Runs APScheduler to trigger data retrieval every 5 seconds
- Manages timeframe flip detection (when a new candle period begins)
- Handles graceful shutdown and log archival

**Data Structures**:
```python
DR_queue: Queue()           # Watchlist symbols for data retrieval
ticker_queues: [Queue()]    # Per-symbol price data
broker_queue: Queue()       # Trade signals to broker
TF: {"m5": True, ...}       # Timeframe flip indicators
```

**Scheduling Logic**:
```python
def scheduling(symbols, DR_queue, DR_condition, TF, TF_condition, opening_time, time_quant=5):
    # 1. Put watchlist into DR queue
    # 2. Notify DataRetrieval thread
    # 3. Detect timeframe flips (m5, m15, m30, m60, d, w, m, q)
    # 4. Notify all Ticker threads
```

---

### 2. DataRetrieval.py - Market Data Fetcher
**Purpose**: Threaded component that retrieves real-time market data

**Key Responsibilities**:
- Waits for scheduler signal via `DR_condition`
- Fetches latest 1-minute bar data for all watchlist symbols via Alpaca API
- Pushes closing prices to individual ticker queues
- Provides initial historical data (4 bars per timeframe) on startup

**API Usage**:
```python
# Real-time latest bar request
request_params = StockLatestBarRequest(
    symbol_or_symbols=self.watchlist,
    timeframe=TimeFrame.Minute
)
bar = self.session.get_stock_latest_bar(request_params)

# Historical bars for initialization
request_params = StockBarsRequest(
    symbol_or_symbols=symbol,
    timeframe=timeframe,
    start=startdate,
    end=enddate,
    sort=Sort.DESC
)
```

**Initialization Data**: Fetches 4 historical bars per timeframe to establish 3-candle pattern history (current + 2 previous + 1 for previous_high/low reference)

---

### 3. Ticker.py - Per-Symbol Analysis Engine
**Purpose**: Individual thread per ticker that maintains candle history and evaluates trading strategies

**State Management**:
```python
self.candles = {
    "m5": [Candle_live, Candle_prev1, Candle_prev2],
    "m15": [...],
    ...
}
self.status = TickerStatus.OUT | LONG | SHORT
self.entryPrice, self.stopPrice, self.targetPrice
self.strategies = [Strategy(), ...]
```

**Update Cycle** (every 5 seconds):
1. **Wait** for price data from DataRetrieval thread
2. **Update Close**: Set close price of all live candles to latest market price
3. **Update High/Low**: Adjust if new price exceeds current high/low
4. **Create Candles**: If timeframe flipped, insert new candle and pop oldest
5. **Evaluate Strategies**: Check each strategy's score against threshold
6. **Send Signals**: If triggered, push symbol to broker queue

**Candle Creation Logic**:
```python
def createCandle(self, price, timestamp):
    for tf in self.TF:
        if self.TF[tf]:  # Timeframe flipped
            prev_high = candles[0].high
            prev_low = candles[0].low
            newCandle = Candle(timestamp, price, price, price, price, 
                              prev_high, prev_low)
            candles.insert(0, newCandle)
            candles.pop()  # Maintain 3-candle window
```

---

### 4. strategy.py - Strategy Definition & Scoring
**Purpose**: Defines trading strategies with weights, penalties, and thresholds

**Configuration** (from config.toml):
```toml
[[strategies]]
name = "Weighted strat"
type = "Long"
threshold = 3

[strategies.weights]
m60 = 1
d = 1
w = 1
m = 1

[strategies.penalties]
m60 = -1
d = -2
w = -3
m = -4
```

**Scoring Algorithm**:
```python
def checkScore(self, data):
    self.score = 0
    if self.type == "Long":
        for w in self.weights:
            if data[w][0].get_kind() == "2" and data[w][0].get_subtype() == "U":
                # Directional breakout UP
                self.score += self.weights[w]
            else:
                self.score += self.penalties[w]
        
        if self.score >= self.threshold:
            self.status = TickerStatus.LONG
            return self.status
```

**Logic**: Sum weights for bullish signals (2U candles), apply penalties otherwise. If score ≥ threshold, trigger LONG entry.

---

### 5. candles.py - Candlestick Classification
**Purpose**: Analyzes individual candles to determine kind, direction, and pattern

**Candle Structure**:
```python
class Candle:
    timestamp_ms   # Opening time in milliseconds
    open, high, low, close
    previous_high, previous_low  # For pattern comparison
```

**Classification System**:

#### Kind (relationship to previous candle's range):
- **Kind 1 (Inside)**: `high ≤ prev_high AND low ≥ prev_low`
  ```
   _
  | |_
  | |_|  <- Inside previous candle
  |_|
  ```

- **Kind 2 (Directional)**: Breaks in one direction only
  ```
     _
   _| |   <- Breaks high (2U)
  | |_|
  |_|
  ```

- **Kind 3 (Outside)**: `high > prev_high AND low < prev_low`
  ```
     _
   _| |
  |_| |   <- Engulfs previous candle
    |_|
  ```

#### Subtype (for Kind 2):
- **2U (Up)**: `high > prev_high`
- **2D (Down)**: `low < prev_low`

#### Direction:
- **G (Green)**: `close ≥ open` (bullish body)
- **R (Red)**: `close < open` (bearish body)

#### Pattern:
- **H (Hammer)**: Open/close in top 30% of range (long lower wick)
- **S (Shooter)**: Open/close in bottom 30% of range (long upper wick)
- **X**: Neither

**String Representation**: `to_string()` returns `"2UGH"` → Kind 2, Up, Green, Hammer

---

### 6. patterns.py - Pattern Recognition
**Purpose**: Detects specific multi-candle patterns for entry/exit signals

#### Bullish Reversal 2-1-2:
```
   __    __
__|  |__|  |
  |2D|  |2U|  <- Entry: 2D → 1 → 2U
  |  | 1|__|
  |  |__|
  |  |
  |__|
```

**Logic**:
```python
def bullish_reversal_212(data):
    if (data[0].get_kind() == "2" and data[0].get_subtype() == "D") and \
       (data[1].get_kind() == "1"):
        if data[2].open > data[1].low and data[2].get_kind() != "3":
            entry = data[1].high
            target = data[0].high
            stop = data[1].low
            return (entry, target, stop)
    return (-1, -1, -1)
```

**Pattern Requirements**:
1. Most recent candle (data[0]): Kind 2, Down direction
2. Previous candle (data[1]): Kind 1 (inside)
3. Two candles ago (data[2]): Opens above inside candle's low, not Kind 3

#### Bearish Reversal 2-1-2:
Similar logic but reversed: 2U → 1 → 2D

---

### 7. Broker.py - Trade Execution Stub
**Purpose**: Receives trade signals and executes orders (currently incomplete)

**Current Implementation**:
```python
def run(self):
    while True:
        with self.broker_condition:
            self.broker_condition.wait()
        while not self.input_queue.empty():
            symbol = self.input_queue.get(timeout=1)
            # TODO: Execute order via Alpaca Trading API
```

**Planned Functionality**:
- Position sizing based on account equity
- Order placement (market/limit orders)
- Stop-loss and take-profit management
- Position tracking and exit logic

---

### 8. alpaca_chart.py - Alpaca API Integration
**Purpose**: Handles all communication with Alpaca markets API

**Key Features**:
- **Rate Limiting**: `SharedRateLimiter` enforces 200 requests/minute limit
  ```python
  class SharedRateLimiter:
      def __init__(self, max_requests_per_minute=200):
          self.timestamps = manager.list()  # Multiprocess-safe
          
      def acquire(self):
          # Remove timestamps older than 60 seconds
          # If under limit, add timestamp and proceed
          # Otherwise, calculate wait time and sleep
  ```

- **Database Caching**: `ChartDB` (SQLite) stores historical candles to minimize API calls

- **Market Time Management**: Integrates `MarketTimeManager` for:
  - NYSE trading calendar
  - Timezone conversions (EST/PT)
  - Timeframe period calculations

**DataRetrieval Class**:
```python
def getChart(self, symbols, timeframe, start_ts, end_ts):
    # Check DB cache first
    # If missing, fetch from Alpaca API
    # Store in cache for future use
    # Return as list of Candle objects
```

---

### 9. BackTester.py - Historical Strategy Validation
**Purpose**: Simulates trading strategies on historical data to evaluate performance

**Supported Strategies**:
1. **SimpleDailyAS**: Entry on daily actionable signals
2. **LTFEntryOnHTFSignal**: Lower timeframe entry on higher timeframe signal
3. **SimpleAS_DailyTFCStop**: Daily AS with trailing from close stop

**Trade Lifecycle**:
```python
def enterTrade(sym, chartDictNew, chartDictOld, session, strategy):
    # 1. Screen daily+HTF charts for potential trade
    potentialTrade = strategy.screenTrade(chartDictNew, chartDictOld)
    
    # 2. If triggered, fetch intraday (1min) chart
    intradayCandles = session.getChart([sym], 'm1', tradeDay[0], tradeDay[1])
    
    # 3. Find exact entry time when trigger price hit
    entryID = next(ii for ii, candle in enumerate(intradayCandles) 
                   if candle.high > triggerPrice)
    
    # 4. Record entry details
    currentTrade = {
        'symbol': sym,
        'entryPrice': triggerPrice,
        'entryTimestamp_sec': entryTimestamp,
        'direction': LONG/SHORT,
        'stop': stopPrice,
        'target': targetPrice
    }
    
    # 5. Track exits (stop hit, target hit, counter-trend signal)
```

**Multiprocessing Support**:
```python
# Rate limiter shared across worker processes
shared_limiter = SharedRateLimiter(manager=Manager())

# Parallel backtesting with partial function
with mp.Pool(initializer=init_pool, initargs=(shared_limiter,)) as pool:
    results = pool.map(backtest_worker, param_combinations)
```

**Performance Metrics**:
- Entry/exit prices and timestamps
- Days open per trade
- P&L per trade and cumulative
- Win rate, average win/loss
- Stop types (hit, gapped, same-day)

---

### 10. BackTestStrategy.py - Strategy Implementations
**Purpose**: Defines specific backtesting strategy logic

**SimpleDailyAS Strategy**:
```python
def screenTrade(self, chartDictNew, chartDictOld):
    # Check if daily candle forms actionable signal
    if chartDictNew['d'][-1].is_AS():
        triggerPrice = chartDictNew['d'][-1].high  # For LONG
        return [(triggerPrice, TickerStatus.LONG)]
    return False

def exitTrade(self, currentTrade, chartDict):
    # Exit on counter-trend daily AS
    if chartDict['d'][-1].is_counter_AS(currentTrade['direction']):
        exitPrice = chartDict['d'][-1].low  # For LONG exit
        return (exitPrice, 'counter-trend AS')
    return None
```

---

### 11. chartDB.py - SQLite Caching Layer
**Purpose**: Persistent storage for historical candle data to reduce API calls

**Schema**:
```sql
CREATE TABLE candles (
    symbol TEXT,
    timeframe TEXT,
    timestamp_ms INTEGER,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, timeframe, timestamp_ms)
)
```

**Usage Pattern**:
```python
# Check cache first
cached_data = db.get_candles(symbol, timeframe, start_ts, end_ts)

if cached_data.missing_periods:
    # Fetch from API
    api_data = alpaca_fetch(symbol, timeframe, missing_start, missing_end)
    
    # Store in cache
    db.store_candles(symbol, timeframe, api_data)

return cached_data + api_data
```

---

### 12. MarketTimeManager.py - Calendar & Time Management
**Purpose**: Handles market hours, holidays, and timeframe conversions

**Key Functions**:
```python
def getTodayOpenTime_ms():
    # Returns NYSE opening time (9:30 AM EST) in milliseconds

def detectTFFlip(current_time, timeframe_minutes, time_quant):
    # Detects when a new candle period begins
    # Example: At 10:00:00, 60min candle flips
    
def getCandleOpenCloseTime(timestamp, timeframe, n_pre, n_post):
    # Returns {'pre': [...], 'current': (open, close), 'post': [...]}
    # Accounts for market holidays and short trading days
```

**Market Calendar Integration**:
- Uses `pandas_market_calendars` for NYSE schedule
- Handles early closes (e.g., day before Thanksgiving)
- Timezone conversions between EST and local time

---

### 13. util.py - Utilities & Configuration
**Purpose**: Common utilities, enums, and configuration loading

**Key Components**:

#### TickerStatus Enum:
```python
class TickerStatus(Enum):
    OUT = 0    # No position
    LONG = 1   # Long position
    SHORT = 2  # Short position
```

#### Timeframe Lookup Table:
```python
timeframe_LUT = {
    "m5": (5, "minute"),
    "m15": (15, "minute"),
    "m30": (30, "minute"),
    "m60": (60, "minute"),
    "d": (1440, "day"),      # 24 hours * 60 min
    "w": (10080, "week"),     # 7 days * 1440 min
    "m": (43200, "month"),    # 30 days * 1440 min
    "q": (129600, "quarter")  # 90 days * 1440 min
}
```

#### Configuration Loading:
```python
def loadStrategies():
    # Reads config.toml
    # Returns list of strategy dictionaries
    with open("config.toml", "r") as f:
        config = toml.load(f)
    return config['strategies']

def loadSymbols():
    # Loads watchlist from Watchlists directory
```

#### Logging Setup:
```python
def strat_logger(name, logfile):
    # Creates per-ticker logger
    # Logs to file and console
    # Supports debug/info/warning/error levels
```

#### Time Utilities:
```python
def getProperStartTime(current_time, time_quant):
    # Rounds current time to next time_quant boundary
    # Example: 9:32:17 with quant=5 → 9:32:20
```

---

### 14. Additional Modules

#### earnings_calendar.py:
**Purpose**: Tracks earnings announcement dates
- Fetches earnings calendar data
- Avoids trading around earnings (high volatility)
- Stored as CSV: `EarningsCalendar_YYYY-MM-DD.csv`

#### session.py:
**Purpose**: Session management for API connections
- Initializes Alpaca session with API keys
- Manages authentication state

#### bot.py:
**Purpose**: Standalone pattern detection testing utility
- Interactive pattern validation
- Chart visualization for debugging

#### determineBestCombo_FeatureImportance.py:
**Purpose**: Strategy parameter optimization
- Grid search over weight/penalty combinations
- Feature importance analysis
- Backtesting-based evaluation

#### candleChangeTest.py:
**Purpose**: Unit testing for candle update logic
- Validates high/low updates
- Tests candle flip detection

#### updater.py:
**Purpose**: Database maintenance utilities
- Updates historical data in chartDB
- Fills gaps in cached data

#### log_functions.py:
**Purpose**: Advanced logging utilities
- Multi-process logging support
- Log queue management for parallel backtesting

---

## Data Flow & Execution

### Typical Trading Day Flow:

```
[9:30:00 AM] Market opens
             ↓
[9:30:00] Main.py starts APScheduler
          Initializes: DataRetrieval, Broker, Ticker(TSLA, AAPL, QQQ, SQQQ)
          Loads strategies from config.toml
          Fetches initial 4 bars per timeframe
             ↓
[9:30:05] Scheduler → scheduling()
          - Puts watchlist into DR_queue
          - Detects TF flips (m5, m15, m30, m60 all flip at market open)
          - Notifies DataRetrieval thread
             ↓
[9:30:06] DataRetrieval.run()
          - Fetches latest 1min bars for [TSLA, AAPL, QQQ, SQQQ]
          - Pushes close prices to ticker_queues[0..3]
          - Notifies all Ticker threads
             ↓
[9:30:07] Ticker(TSLA).run()
          - Receives close price (e.g., $850.25)
          - Updates close on all live candles
          - Updates high/low if price exceeds current
          - Creates new m5, m15, m30, m60 candles (TF flipped)
          - Evaluates strategies:
              Strategy "Weighted strat":
                - Check m60[0]: Kind=2, Subtype=U → +1 (weight)
                - Check d[0]: Kind=1 → -2 (penalty)
                - Check w[0]: Kind=2, Subtype=U → +1 (weight)
                - Check m[0]: Kind=2, Subtype=D → -4 (penalty)
                - Score = 1 + (-2) + 1 + (-4) = -4 < threshold (3)
                - Status remains OUT
             ↓
[9:30:08] Ticker sends "TSLA" to broker_queue
          Notifies Broker thread
             ↓
[9:30:08] Broker.run()
          - Receives "TSLA"
          - TODO: Execute order (stub)
             ↓
[9:30:10] Scheduler → scheduling() [2nd iteration]
          - Detects no TF flips (no candle boundaries crossed)
          - Repeats cycle
             ↓
[10:00:00] 60min candle flips!
           TF['m60'] = True
           Ticker creates new 60min candle
           Re-evaluates strategy with fresh candle
             ↓
[3:55:00 PM] Daily candle near completion
             Live candle high/low continuously updated
             Strategy scores adjust in real-time
             ↓
[4:00:00 PM] Market closes
             Daily candle flips
             Ticker evaluates final scores
             If score ≥ threshold → signal sent to Broker
```

### Example: TSLA Long Entry Scenario

**Setup**:
- Weekly chart: 2U (bullish breakout)
- Monthly chart: 2U (bullish breakout)
- Daily chart: 1 (inside day, consolidation)
- 60min chart: 2D (pullback)

**Time: 2:15 PM**:
- Latest price: $852.50
- 60min candle flips to 2U (breaks above previous 60min high)
- Strategy "Weighted strat" scoring:
  ```
  m60: 2U → +1
  d:   1  → -2
  w:   2U → +1
  m:   2U → +1
  Score = 1 + (-2) + 1 + 1 = 1 < 3 (threshold)
  Status: OUT
  ```

**Time: 3:45 PM**:
- Latest price: $855.75
- Daily candle transitions from Kind 1 to Kind 2U (breaks daily high)
- Strategy rescores:
  ```
  m60: 2U → +1
  d:   2U → +1  (changed!)
  w:   2U → +1
  m:   2U → +1
  Score = 1 + 1 + 1 + 1 = 4 ≥ 3 (threshold)
  Status: LONG
  ```
- Ticker sends "TSLA" to broker_queue
- Broker receives signal → TODO: Buy TSLA at market

---

## External Dependencies

### Primary Broker API: Alpaca
```python
alpaca-py >= 0.10.0
alpaca-trade-api >= 3.0.2
```

**Usage**:
- **Market Data**: `StockHistoricalDataClient`
  - Real-time latest bars (`StockLatestBarRequest`)
  - Historical OHLCV data (`StockBarsRequest`)
  - Multiple timeframes: Minute, Hour, Day, Week, Month
  - Rate limit: 200 requests/minute

- **Trading** (planned): `TradingClient`
  - Order placement (market, limit, stop)
  - Position management
  - Account information

- **Market Calendar**: NYSE trading hours, holidays

### Secondary Broker: TD Ameritrade
```python
td-ameritrade-python-api >= 0.3.5
```
- Legacy support (partially broken timezone handling)
- Referenced in TODOs but not actively used

### Data Processing:
```python
pandas >= 2.2.2              # DataFrame manipulation
numpy >= 1.23.5              # Numerical operations
pandas_market_calendars >= 4.4.0  # NYSE calendar
```

### Scheduling & Threading:
```python
APScheduler >= 3.10.3        # Background job scheduling
# Standard library: threading, queue, multiprocessing
```

### Configuration & Utilities:
```python
tomlkit >= 0.12.1            # config.toml parsing
pytz >= 2022.6               # Timezone handling (EST/PT)
tzdata >= 2022.7             # Timezone database
python-dateutil >= 2.8.2     # Date parsing
requests >= 2.31.0           # HTTP client
PyYAML >= 6.0                # YAML support
```

### Database:
- **SQLite** (standard library): chartDB.db for candle caching

---

## Key Concepts

### Multi-Timeframe Analysis
The bot analyzes 8 timeframes simultaneously:

| Timeframe | Minutes | Use Case |
|-----------|---------|----------|
| m5        | 5       | Intraday entry refinement |
| m15       | 15      | Short-term trend |
| m30       | 30      | Intraday momentum |
| m60       | 60      | Hourly trend confirmation |
| d         | 1440    | Primary trend (daily charts) |
| w         | 10080   | Weekly trend (swing trading) |
| m         | 43200   | Monthly trend (position trading) |
| q         | 129600  | Quarterly trend (macro view) |

**Hierarchy**: Higher timeframes have more weight in strategy scoring. A monthly 2U candle is a stronger signal than a 60min 2U.

### Weighted Strategy Scoring
**Philosophy**: Confluence of signals across timeframes increases conviction.

**Example Configuration**:
```toml
[strategies.weights]    # Awarded when timeframe shows bullish signal
m60 = 1
d = 1
w = 1
m = 1

[strategies.penalties]  # Applied when timeframe shows bearish signal
m60 = -1
d = -2                  # Heavier penalty (daily chart critical)
w = -3                  # Even heavier (weekly trend very important)
m = -4                  # Strongest penalty (monthly trend is king)
```

**Interpretation**:
- **Score = 4**: All timeframes aligned bullish → Strong LONG signal
- **Score = 0**: Mixed signals → No entry
- **Score = -8**: All timeframes bearish → Strong SHORT signal (if threshold negative)

### Candle Kinds & Patterns
**Kind System** enables:
1. **Volatility Detection**: Kind 3 (outside) = high volatility, avoid or use wider stops
2. **Consolidation Recognition**: Kind 1 (inside) = consolidation, prepare for breakout
3. **Trend Confirmation**: Kind 2 (directional) = trend in motion, ride momentum

**2-1-2 Reversal Pattern**:
- **Setup**: Trend (2D/2U) → Consolidation (1) → Reversal (2U/2D)
- **Psychology**: Sellers exhaust (2D), market pauses (1), buyers take control (2U)
- **Entry**: Break of inside candle high/low confirms reversal

### Timeframe Flipping
**Concept**: A new candle begins when the time period rolls over.

**Example** (60min candle):
```
9:00 - 9:59   → 60min candle #1 (live, updating)
10:00 - 10:59 → 60min candle #2 (NEW candle created)
```

**Detection**:
```python
def detectTFFlip(current_time, timeframe_minutes, time_quant):
    # Check if we crossed a timeframe boundary
    prev_time = current_time - timedelta(seconds=time_quant)
    
    prev_period = prev_time.minute // timeframe_minutes
    curr_period = current_time.minute // timeframe_minutes
    
    return curr_period != prev_period
```

**Impact**:
- Live candle → Becomes 2nd candle in array
- New live candle created with: `open = high = low = close = current_price`
- Previous high/low from old live candle

### Rate Limiting & Caching
**Challenge**: Alpaca limits to 200 requests/minute

**Solution 1 - SharedRateLimiter**:
```python
# Multiprocess-safe sliding window rate limiter
def acquire(self):
    # Keep last 60 seconds of timestamps
    # If count < 200: proceed
    # Else: sleep until oldest timestamp ages out
```

**Solution 2 - chartDB Caching**:
```
Request for AAPL daily bars, 2024-01-01 to 2024-12-31:
    ↓
Check chartDB.db:
    - Found: 2024-01-01 to 2024-06-30 (180 bars)
    - Missing: 2024-07-01 to 2024-12-31 (154 bars)
    ↓
Fetch only missing data from Alpaca (1 API call instead of full range)
    ↓
Store new data in chartDB
    ↓
Return combined cached + fetched data
```

**Result**: Reduces API calls by ~90% for backtesting.

---

## Configuration

### config.toml Structure:
```toml
[[strategies]]              # Array of strategies
name = "Weighted strat"
type = "Long"               # "Long" or "Short"
threshold = 3               # Minimum score to trigger entry

[strategies.weights]        # Points awarded for bullish signals
m60 = 1
d = 1
w = 1
m = 1

[strategies.penalties]      # Points deducted for bearish signals
m60 = -1
d = -2
w = -3
m = -4

[strategies.exit]           # Exit conditions
type = "counter-trend"
m60 = -1                    # Exit if 60min shows counter-trend

[strategies.tfc]            # Trailing From Close (TODO: not implemented)

[paths]                     # File paths
logs = '/Users/sepy/Library/Mobile Documents/com~apple~CloudDocs/logs/'
```

### Watchlist Configuration:
Currently hardcoded in `Main.py`:
```python
watchlist = ["TSLA", "AAPL", "QQQ", "SQQQ"]
```

**Future**: Load from `Watchlists/` directory or database.

### Alpaca Configuration:
Stored in `alpaca_config.py` (not in repo, user-provided):
```python
alpaca_config = {
    'key': 'YOUR_API_KEY',
    'secret_key': 'YOUR_SECRET_KEY',
    'base_url': 'https://paper-api.alpaca.markets'  # Paper trading
}
```

---

## Current Limitations & TODOs

### Known Issues:
1. **Broker Integration Incomplete**: 
   - `Broker.py` receives signals but doesn't execute orders
   - Need to implement position sizing, order placement, stop management

2. **Timeframe Flip Detection**:
   - Doesn't account for market hours (may flip during pre-market)
   - Short trading days (early close) not validated

3. **TD Ameritrade Support**:
   - Timezone handling broken
   - Not actively maintained

4. **Pattern Validation**:
   - No validation for short trading days
   - Doesn't exclude holidays or half-days

5. **Logging**:
   - Log files accumulate, need rotation
   - `moveLogs()` requires manual cloud sync path

### Planned Features:
- **Telegram Bot**: Real-time trade notifications
- **Web Dashboard**: Live monitoring of positions and signals
- **Risk Management**: Position sizing based on volatility (ATR)
- **Multiple Strategies**: Run different strategies per symbol
- **Paper Trading Validation**: Extended testing before live deployment

---

## Getting Started

### Prerequisites:
1. Python 3.10+ (uses match/case syntax)
2. Alpaca account (paper trading)
3. API keys from Alpaca

### Installation:
```bash
# Clone repository
git clone https://github.com/sepy97/stratBot.git
cd stratBot

# Install dependencies
pip install -r requirements.txt

# Create alpaca_config.py
echo "alpaca_config = {'key': 'YOUR_KEY', 'secret_key': 'YOUR_SECRET'}" > alpaca_config.py
```

### Running the Bot:
```bash
# Start the bot
python Main.py

# Output:
# Proper start time: 2024-01-15 09:30:00
# Opening time: 2024-01-15 09:30:00
# Timeframe d flipped: True at time 2024-01-15 09:30:05
# Ticker TSLA has candles at time 09:30:07: ...
```

### Backtesting:
```bash
# Run backtest with SimpleDailyAS strategy
python BackTester.py --symbol AAPL --start 2023-01-01 --end 2023-12-31
```

### Testing Patterns:
```bash
# Interactive pattern tester
python bot.py
```

---

## Summary

**stratBot** is a sophisticated multi-timeframe algorithmic trading system that:
- Monitors markets in real-time via Alpaca API
- Analyzes candlestick patterns across 8 timeframes
- Scores trading opportunities using weighted strategies
- Provides comprehensive backtesting capabilities
- Implements rate limiting and caching for efficiency

The architecture is modular, threaded, and designed for extensibility. While the core analysis engine is complete, order execution remains a stub, making this ideal for paper trading validation before live deployment.
