import sqlite3
import pandas as pd
import time
from datetime import datetime
from typing import Optional, Callable, List, Tuple, Union
from itertools import product

# Optional: for testing only
from collections import namedtuple
StockBarsRequest = namedtuple("StockBarsRequest", ["symbol_or_symbols", "timeframe", "start", "end"])


class ChartDB:
    def __init__(self, db_path: str):
        """
        db_path: SQLite DB file path (use ':memory:' for in-memory DB)
        """
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()
    # --------------------------------------------------------
    # Schema setup
    # --------------------------------------------------------
    def _init_schema(self):
        """Create candles table if not exists."""
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            trade_count REAL,
            vwap REAL,
            PRIMARY KEY (symbol, timeframe, timestamp)
        )
        """)
        self.conn.commit()

    # --------------------------------------------------------
    # DB operations
    # --------------------------------------------------------
    def insert_candles(self, timeframe: str, df_org: pd.DataFrame):
        """
        Insert a DataFrame of candles into DB.

        - Accepts BOTH:
            1) Plain DF with 'symbol' and 'timestamp' as columns
            2) MultiIndex DF with (symbol, timestamp) as index

        Will automatically reset index if needed.
        """
        if df_org.empty:
            return
        
        df = df_org.copy()  # Work on a copy to avoid modifying original DataFrame

        # ✅ If DataFrame has MultiIndex, flatten it
        if isinstance(df.index, pd.MultiIndex):
            # Get the timestamp level
            ts_level = df.index.levels[1]

            # Make sure it's tz-aware
            if ts_level.tz is None:
                raise ValueError("[chartDB] Timestamp level must be timezone-aware before inserting.")

            # Convert to EST
            df.index = df.index.set_levels(
                ts_level.tz_convert("America/New_York"), level=1
            )
            df.reset_index(inplace=True)
        # ✅ If DataFrame has single index = timestamp, ensure timestamp is column
        else: 
            raise ValueError("[chartDB] DataFrame must have a MultiIndex with (symbol, timestamp) or a single index with timestamp.")

        # ✅ Ensure required columns exist
        required_cols = {"symbol", "timestamp", "open", "high", "low", "close",
                         "volume", "trade_count", "vwap"}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Missing columns in DataFrame. Got {df.columns}, expected {required_cols}")

        # ✅ Convert timestamp to string for SQLite storage
        #df["timestamp"] = df["timestamp"].astype(str)
        # ✅ Convert timestamp to integer for SQLite storage
        df["timestamp"] = df["timestamp"].astype('int64') // 10**9  # convert to seconds since epoch

        rows = [
            (symbol, timeframe, timestamp, open_, high, low, close, volume, trade_count, vwap)
            for (symbol, timestamp, open_, high, low, close, volume, trade_count, vwap)
            in df.itertuples(index=False, name=None)
        ]

        self.conn.executemany("""
        INSERT OR IGNORE INTO candles
        (symbol, timeframe, timestamp, open, high, low, close, volume, trade_count, vwap)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()

    def get_candles_by_open_timestamp(
        self,
        symbol_or_symbols: Union[str, List[str]], 
        timeframe: str, 
        open_ts: list[pd.Timestamp], 
        max_values_rows: int = 100_000,
        batch_size: int = 50_000) -> pd.DataFrame:

        symbols = symbol_or_symbols if isinstance(symbol_or_symbols, List) else [symbol_or_symbols]
        total_rows = len(symbols) * len(open_ts)
        df_found = pd.DataFrame()

        if total_rows == 0: # nothing to do 
            return df_found
        # Convert timestamps to string for DB comparison
        open_ts_int = [int(ts.timestamp()) for ts in open_ts]

        if total_rows < max_values_rows:
            # --- Small dataset: VALUES() approach ---
            values_clause = ",".join(["(?, ?)"] * total_rows)
            flat_params = []
            flat_params = [item for pair in product(symbols, open_ts_int) for item in pair] # create all possible (symbol, timestamp) pairs
            flat_params.append(timeframe)  # add timeframe as the last parameter
            query = f"""
                SELECT *
                FROM candles
                WHERE (symbol, timestamp) IN (VALUES {values_clause})
                AND timeframe = ?
            """
            df_found = pd.read_sql_query(query, self.conn, params=flat_params)
        else:
            # --- Large dataset: TEMP TABLE + batched inserts ---
            cur = self.conn.cursor()
            cur.execute("DROP TABLE IF EXISTS temp_open_times")
            cur.execute("""
                CREATE TEMPORARY TABLE temp_open_times (
                    symbol TEXT,
                    timestamp INTEGER
                )
            """)
            # Insert in batches
            for start_idx in range(0, len(open_ts_int), batch_size):
                ts_batch = open_ts_int[start_idx:start_idx + batch_size]
                batch_rows = list(product(symbols, ts_batch))
                cur.executemany(
                    "INSERT INTO temp_open_times(symbol, timestamp) VALUES (?, ?)",
                    batch_rows
                )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_temp ON temp_open_times(symbol, timestamp)")
            self.conn.commit()

            # Join temp table with candles
            query = """
                SELECT c.*
                FROM candles c
                JOIN temp_open_times t
                ON c.symbol = t.symbol AND c.timestamp = t.timestamp
                WHERE c.timeframe = ?
            """
            df_found = pd.read_sql_query(query, self.conn, params=[timeframe])
        # --- Post-processing ---
        if not df_found.empty:
            df_found['timestamp'] = pd.to_datetime(df_found['timestamp'], unit='s', utc=True).dt.tz_convert('America/New_York')
            df_found.drop(columns=['timeframe'], inplace=True)
            df_found.set_index(['symbol', 'timestamp'], inplace=True)
            df_found.sort_index(inplace=True)
        return df_found
    '''
    def get_candles(self, symbols: Union[str, List[str]], timeframe: str,
                    start: Optional[pd.Timestamp] = None,
                    end: Optional[pd.Timestamp] = None,
                    chunk_size: int = 800) -> pd.DataFrame:
        """
        Query candles for one or many symbols.

        - Single symbol: returns DF indexed by timestamp.
        - Multi-symbol: returns DF with MultiIndex [symbol, timestamp].
        """
        if isinstance(symbols, str):
            symbols = [symbols]  # unify to list
        dfs = []
        start = start.timestamp() if start is not None else None
        end = end.timestamp() if end is not None else None
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i+chunk_size]

            placeholders = ",".join("?" for _ in chunk)
            q = f"""
            SELECT symbol, timestamp, open, high, low, close, volume, trade_count, vwap
            FROM candles
            WHERE symbol IN ({placeholders}) AND timeframe = ?
            """
            params = symbols + [timeframe]

            if start is not None:
                q += " AND timestamp >= ?"
                params.append(str(start))
            if end is not None:
                q += " AND timestamp <= ?"
                params.append(str(end))
            q += " ORDER BY symbol, timestamp ASC"

            #df_chunk = pd.read_sql_query(q, self.conn, params=params, parse_dates=["timestamp"])
            df_chunk = pd.read_sql_query(q, self.conn, params=params)
            dfs.append(df_chunk)

        if not dfs:
            return pd.DataFrame()

        df = pd.concat(dfs)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='s', utc=True).dt.tz_convert("America/New_York")
        df.set_index(["symbol", "timestamp"], inplace=True)
        return df
    
    def get_existing_range(self, symbol: str, timeframe: str) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
        """Return (min_timestamp, max_timestamp) for a given symbol/timeframe in DB."""
        cur = self.conn.execute("""
            SELECT MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
            FROM candles
            WHERE symbol = ? AND timeframe = ?
        """, (symbol, timeframe))
        row = cur.fetchone()
        if row["min_ts"] is None or row["max_ts"] is None:
            return None, None
        return (pd.Timestamp(row["min_ts"]), pd.Timestamp(row["max_ts"]))
    '''
    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------
    '''
    def find_missing_ranges(self, symbols: Union[str, List[str]], timeframe: str, start: pd.Timestamp, end: pd.Timestamp) -> List[Tuple[str, pd.Timestamp, pd.Timestamp]]:
        """
        For each symbol, find missing candle ranges in the DB.
        Returns: list of (symbol, missing_start, missing_end) tuples
        Assumes DB will hold continuous blocks for each symbol/timeframe.
        """
        if timeframe == "1Min":
            offset = pd.Timedelta(minutes=1)
        elif timeframe == "1Day":
            offset = pd.Timedelta(days=1)
        elif timeframe == "1Week":
            offset = pd.Timedelta(weeks=1)
        elif timeframe == "1Month":
            offset = pd.Timedelta(days=30)
        if isinstance(symbols, str):
            symbols = [symbols]

        missing = []
        query = """
            SELECT MIN(timestamp), MAX(timestamp)
            FROM candles
            WHERE symbol=? AND timeframe=?
            AND timestamp BETWEEN ? AND ?
        """
        for symbol in symbols:
            cur = self.conn.cursor()
            cur.execute(query, (symbol, timeframe, str(start), str(end)))
            min_ts, max_ts = cur.fetchone()

            if min_ts is None or max_ts is None:
                # Entire range missing for this symbol
                missing.append((symbol, start, end))
                continue
            min_ts, max_ts = pd.to_datetime(min_ts), pd.to_datetime(max_ts)

            # Missing block at the start?
            if start < min_ts:
                if timeframe == "1Min":
                    missing.append((symbol, start, min_ts - pd.Timedelta(minutes=1)))
                elif timeframe == "1Day":
                    missing.append((symbol, start, min_ts.replace(hour=0, minute=0, second=0) - pd.Timedelta(days=1)))
                elif timeframe == "1Week":
                    missing.append((symbol, start, min_ts.replace(hour=0, minute=0, second=0) - pd.Timedelta(days=min_ts.weekday() + 1)))
                elif timeframe == "1Month":
                    month_start = min_ts.replace(day=1, hour=0, minute=0, second=0)
                    missing.append((symbol, start, min_ts.replace(day=1, hour=0, minute=0, second=0) - pd.DateOffset(months=1)))
                elif timeframe == "3Month":
                    missing.append((symbol, start, min_ts.replace(day=1, hour=0, minute=0, second=0) - pd.DateOffset(months=min_ts.month % 3 + 3)))
                elif timeframe == "12Month":
                    missing.append((symbol, start, min_ts.replace(month=1, day=1, hour=0, minute=0, second=0) - pd.DateOffset(years=1)))
            # Missing block at the end?
            if end > max_ts:
                missing.append((symbol, max_ts + pd.Timedelta(minutes=1), end))

        return missing
    '''
    '''
    def get_data_bounds(self, symbols: Union[str, List[str]], tf: str) -> List[Tuple[str, Optional[pd.Timestamp], Optional[pd.Timestamp]]]:
        # Returns the date range for each symbol. 
        # Input timeframe in format '1Day', '1Week', '1Month' etc. (str of TimeFrame enum)
        # Output format: 
        #   List of tuples (symbol, timestamp of the first candle, timestamp of the last candle). 
        #   All timestamps are in EST timezone.
        if isinstance(symbols, str):
            symbols = [symbols]
        #if not any(sub in tf for sub in ['Day', 'Week', 'Month']):
        #    print(f"Warning: get_data_bounds is only for D, W, M TFs. Timeframe provided:{tf}")
        min_ts = None
        max_ts = None
        cur = self.conn.cursor()
        output = []
        for symbol in symbols:
            cur.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM candles WHERE symbol=? AND timeframe=?",
                (symbol, tf)
            )
            min_ts, max_ts = cur.fetchone()
            output.append((symbol, 
                           pd.to_datetime(min_ts, unit='s').tz_localize('UTC').tz_convert('America/New_York') if min_ts else None, 
                           pd.to_datetime(max_ts, unit='s').tz_localize('UTC').tz_convert('America/New_York') if max_ts else None))
        return output
    
    def _fetch_from_alpaca(self, request_params):
        """
        Retry wrapper for Alpaca fetch calls.
        self.alpaca_fetch_func(request_params) must return a DataFrame.
        """
        attempts = self.MAX_RETRIES
        while attempts > 0:
            try:
                return self.alpaca_fetch_func(request_params)
            except Exception as e:
                attempts -= 1
                if attempts == 0:
                    print(f"[ChartDB] Error fetching {request_params.symbol_or_symbols} {request_params.timeframe}: {e}")
                    raise
                else:
                    print(f"[ChartDB] Error: {e} – retrying in 60s ({self.MAX_RETRIES - attempts}/{self.MAX_RETRIES})")
                    time.sleep(60)
    '''
    # --------------------------------------------------------
    # Maintenance utilities
    # --------------------------------------------------------
    def delete_symbol(self, symbol: str, timeframe: Optional[str] = None):
        """Delete all candles for symbol, or just for a specific timeframe."""
        with self.conn:
            if timeframe:
                self.conn.execute("DELETE FROM candles WHERE symbol = ? AND timeframe = ?", (symbol, timeframe))
            else:
                self.conn.execute("DELETE FROM candles WHERE symbol = ?", (symbol,))
        self.conn.commit()

    def delete_all(self):
        """Delete ALL candles."""
        with self.conn:
            self.conn.execute("DELETE FROM candles")
        self.conn.commit()

    def summary(self, symbol: str):
        """Print summary of timeframes and data ranges for a symbol."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT timeframe,
                   MIN(timestamp),
                   MAX(timestamp),
                   COUNT(*)
            FROM candles
            WHERE symbol = ?
            GROUP BY timeframe
        """, (symbol,))
        rows = cursor.fetchall()
        if not rows:
            print(f"No data for {symbol}")
            return
        print(f"Summary for {symbol}:")
        for timeframe, start, end, count in rows:
            start = pd.to_datetime(start, unit='s').tz_localize('UTC').tz_convert('America/New_York')
            end = pd.to_datetime(end, unit='s').tz_localize('UTC').tz_convert('America/New_York')
            print(f"  {timeframe}: {start} → {end} ({count} candles)")

    # ----------------------------------------
    # CLEANUP
    # ----------------------------------------
    def close(self):
        self.conn.close()

# ---------------------------------------------------------
# TEST MAIN (runs only if you execute chartDB.py directly)
# ---------------------------------------------------------
if __name__ == "__main__":
    db = ChartDB("chartDB_test.db")
    db.delete_all()

    # Make some fake data for two symbols
    idx = pd.date_range("2025-07-30 09:30", periods=3, freq="1min", tz="America/New_York")
    df_aapl = pd.DataFrame({
        "open": [195, 196, 197],
        "high": [196, 197, 198],
        "low": [194, 195, 196],
        "close": [195.5, 196.5, 197.5],
        "volume": [1000, 1100, 1200],
        "trade_count": [10, 11, 12],
        "vwap": [195.2, 196.2, 197.2],
    }, index=pd.MultiIndex.from_product([["AAPL"], idx], names=["symbol", "timestamp"]))

    # ✅ Create fake data for MSFT (offset values)
    df_msft = df_aapl.copy()
    df_msft.index = pd.MultiIndex.from_product([["MSFT"], idx], names=["symbol", "timestamp"])
    df_msft[["open", "high", "low", "close", "vwap"]] += 50
    df_msft["volume"] += 500

    # Insert for AAPL and MSFT
    db.insert_candles("m1", df_aapl)
    db.insert_candles("m1", df_msft)

    # Query single symbol
    print("\nAAPL:")
    print(db.get_candles_by_open_timestamp("AAPL", "m1", idx.tolist()))

    # Query multiple symbols
    print("\nAAPL & MSFT:")
    print(db.get_candles_by_open_timestamp(["AAPL", "MSFT"], "m1", idx.tolist()))

    # Print summary
    print("\nSummary:")
    db.summary("AAPL")

    '''
    bounds = db.get_data_bounds(["AAPL", "MSFT"], "1Day")
    print("\nData bounds:")
    for symbol, min_ts, max_ts in bounds:
        print(f"{symbol}: {min_ts} to {max_ts}")    

    bounds_nonexistent = db.get_data_bounds(["GOOG"], "1Day")
    print("\nData bounds for nonexistent symbol:")
    for symbol, min_ts, max_ts in bounds_nonexistent:
        print(f"{symbol}: {min_ts} to {max_ts}")

    bounds_mixed = db.get_data_bounds(["AAPL", "GOOG"], "1Day")
    print("\nData bounds for mixed symbols:")
    for symbol, min_ts, max_ts in bounds_mixed:
        print(f"{symbol}: {min_ts} to {max_ts}")    
    '''
    
    db.close()