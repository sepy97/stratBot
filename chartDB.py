import sqlite3
import pandas as pd
import time
from datetime import datetime
from typing import Optional, Callable, List, Tuple, Union

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
            timestamp TEXT NOT NULL,
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
    def insert_candles(self, timeframe: str, df: pd.DataFrame):
        """
        Insert a DataFrame of candles into DB.

        - Accepts BOTH:
            1) Plain DF with 'symbol' and 'timestamp' as columns
            2) MultiIndex DF with (symbol, timestamp) as index

        Will automatically reset index if needed.
        """
        if df.empty:
            return
        
        # ✅ If DataFrame has MultiIndex, flatten it
        if isinstance(df.index, pd.MultiIndex):
            df.reset_index(inplace=True)
        # ✅ If DataFrame has single index = timestamp, ensure timestamp is column
        elif df.index.name == "timestamp":
            df = df.reset_index()

        # ✅ Ensure required columns exist
        required_cols = {"symbol", "timestamp", "open", "high", "low", "close",
                         "volume", "trade_count", "vwap"}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Missing columns in DataFrame. Got {df.columns}, expected {required_cols}")

        # ✅ Convert timestamp to string for SQLite storage
        df["timestamp"] = df["timestamp"].astype(str)

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

            df_chunk = pd.read_sql_query(q, self.conn, params=params, parse_dates=["timestamp"])
            dfs.append(df_chunk)

        if not dfs:
            return pd.DataFrame()

        df = pd.concat(dfs)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index(["symbol", "timestamp"], inplace=True)
        return df
    '''
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
    # DB + API integration
    # --------------------------------------------------------
    def getChartWithPrintout(self, request_params):
        """
        Retrieves candles for one or multiple symbols from request_params.
        - Checks DB first
        - Calls Alpaca for missing ranges
        - Returns DataFrame with MultiIndex (symbol, timestamp)
        """
        if self.alpaca_fetch_func is None:
            raise RuntimeError("ChartDB needs an Alpaca fetch function to fill gaps.")
        db = self._get_db() # ✅ ensures correct ChartDB for this process

        symbols = request_params.symbol_or_symbols
        timeframe = str(request_params.timeframe)
        start = request_params.start
        end = request_params.end
        
        # 📝 Normalize symbols into a list for querying
        symbol_list = symbols if isinstance(symbols, list) else [symbols]

        # 1️⃣ Query DB for what’s there
        df_from_db = self.get_candles(symbol_list, timeframe, start, end)

        # 2️⃣ Determine missing ranges (NOTE: now per-symbol)
        missing_ranges_by_symbol = {}
        for sym in symbol_list:
            df_sym = df_from_db.loc[sym] if sym in df_from_db.index.get_level_values("symbol") else pd.DataFrame()
            missing_ranges = self._find_missing_ranges(df_sym, start, end)
            if missing_ranges:
                missing_ranges_by_symbol[sym] = missing_ranges

        # 3️⃣ ✅ If DB fully covers the range, return immediately
        if not missing_ranges_by_symbol:
            return df_from_db

        # 4️⃣ Fetch missing ranges from Alpaca and insert
        for m_start, m_end in missing_ranges:
            # Build new request for this missing piece
            req = StockBarsRequest(symbol_or_symbols=symbol,
                                   timeframe=request_params.timeframe,
                                   start=m_start,
                                   end=m_end)

            df_new = self._fetch_from_alpaca(req)
            if not df_new.empty:
                self.insert_candles(str(req.timeframe), df_new)

        # 5️⃣ Query DB again — now complete
        return self.get_candles(symbol, timeframe, start, end)

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------
    def find_missing_ranges(self, symbols: Union[str, List[str]], timeframe: str, start: pd.Timestamp, end: pd.Timestamp) -> List[Tuple[str, pd.Timestamp, pd.Timestamp]]:
        """
        For each symbol, find missing candle ranges in the DB.
        Returns: list of (symbol, missing_start, missing_end) tuples
        Assumes DB will hold continuous blocks for each symbol/timeframe.
        """
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
                missing.append((symbol, start, min_ts - pd.Timedelta(minutes=1)))

            # Missing block at the end?
            if end > max_ts:
                missing.append((symbol, max_ts + pd.Timedelta(minutes=1), end))

        return missing

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
    db = ChartDB("test_chartDB.db")
    db.delete_all()

    # Make some fake data for two symbols
    idx = pd.date_range("2025-07-30 09:30", periods=3, freq="1min")
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
    db.insert_candles("1Min", df_aapl)
    db.insert_candles("1Min", df_msft)

    # Query single symbol
    print("\nAAPL:")
    print(db.get_candles("AAPL", "1Min", idx[0], idx[-1]))

    # Query multiple symbols
    print("\nAAPL & MSFT:")
    print(db.get_candles(["AAPL", "MSFT"], "1Min", idx[0], idx[-1]))

    # Print summary
    print("\nSummary:")
    db.summary("AAPL")

    db.close()