from alpaca.data import StockHistoricalDataClient
from datetime import datetime, timedelta
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca_config import alpaca_config
import pandas as pd
import candles
import time
import multiprocessing as mp
import MarketTimeManager as mtm
import os
from chartDB import ChartDB
from multiprocessing import Manager, Lock
from functools import partial
from typing import Optional, Callable, List, Tuple, Union, Dict
from itertools import product
import logging

shared_limiter = None  # Global variable to hold the shared rate limiter instance
logger = logging.getLogger(__name__)

def init_pool(limiter):
    global shared_limiter
    shared_limiter = limiter  # Assign the shared rate limiter to the global variable

class SharedRateLimiter:
    def __init__(self, manager=None, max_requests_per_minute=200):
        self.max_requests = max_requests_per_minute
        self.time_window = 60  # seconds
        if manager is None:
            manager = Manager()
        self.timestamps = manager.list()  # shared list of timestamps
        self.lock = Lock()

    def acquire(self):
        while True:
            now = datetime.now()
            wait_time = 0
            with self.lock:
                # Remove timestamps older than 60 seconds
                one_minute_ago = now - timedelta(seconds=60)
                while self.timestamps and self.timestamps[0] < one_minute_ago:
                    self.timestamps.pop(0)

                if len(self.timestamps) < self.max_requests:
                    self.timestamps.append(now)
                    logger.debug(f"[{mp.current_process().name}] Request allowed at {time.strftime('%X')}")
                    return  # Let the caller proceed
                else:
                    # Need to wait: compute how long until the oldest timestamp expires
                    wait_time = 60 - (now - self.timestamps[0]).total_seconds()
                    logger.debug(f"[{mp.current_process().name}] Rate limit {self.max_requests} hit at {time.strftime('%X')}. Sleeping for {wait_time:.2f} sec.")
                    wait_time = max(wait_time, 0.01)  # minimum wait to avoid tight loop

            # Outside the lock, wait for the quota to open up
            time.sleep(wait_time)


class DataRetrieval:
    def __init__(self, rate_limiter=None, market_time_manager=None, db_path="chartDB.db"):
        #self.db = chartDB.ChartDB(db_path="chartDB.db", alpaca_fetch_func=self._alpaca_fetch)
        self.db = ChartDB(db_path)
        self.rate_limiter = rate_limiter
        self.session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
        self.alpaca_config = alpaca_config
        if market_time_manager is None:
            self.market_time_manager = mtm.MarketTimeManager()
        else:
            self.market_time_manager = market_time_manager
        self.MAX_REQUESTS = 5
        self.aggregation_resample_dict = {'d': 'D', 'w': 'W', 'm': 'ME', 'q': 'QE', 'y': 'YE'}

#    def _get_db(self):
#        pid = os.getpid()
#        if self._db is None or self._pid != pid:
#            self._db = ChartDB(self._db_path)
#            self._pid = pid
#        return self._db
#aggregation_resample_dict = {'d': 'D', 'w': 'W', 'm': 'ME', 'q': 'QE', 'y': 'YE'}

# This function creates a single OHLC dataframe record from a series of smaller TF dataframes (assuming all smaller TF dataframes are for the same symbol)
    def aggregate_barsDF(self, df):
        if not df.empty:
            result = pd.Series({
                #'symbol': df['symbol'].iloc[0],
                'open': df['open'].iloc[0],
                'high': df['high'].max(),
                'low': df['low'].min(),
                'close': df['close'].iloc[-1],
            })
            result["timestamp"]=df.index.get_level_values("timestamp")[0]
            return result

# Returns a dictionary: {symbol --> [list of candles in chronological order (most recent candle last)]}
# First (oldest) candle in the list is the oldest candle that closes after start_timestamp (if start_timestamp is within the candle - it is the first candle; otherwise it is the next candle)
# Last (oldest) candle in the list opens before end_timestamp and closes on end_timestamp (could be partial candle)
# Supported TF: Y, Q, M, W, D, integer hours ('m60', 'm120', etc.), minutes ('m1', 'm5', 'm15', 'm30', etc.)
# start_timestamp and end_timestamp are in seconds
# Implementation detail:
# get_stock_bars behavior: 
#                 Daily and higher timeframes: 
#                 - If start_time does not specify the time (only date) or if the time is 00:00:00EST then the first candle is the one that opens on the date of start_time, 
#                 otherwise it is the candle that opens next. If start_time is not on the trading day then the first candle is the one that opens on the next trading day
#                 - Last bar is always the one that closes at or after the end_time 
#                 - Daily and higher timeframes do not include pre-market or after-hours data
#                 Intraday timeframes:
#                 - If time of start_time is not specified (only date) then the first candle is from the beginning of the premarket of that day
#                 - First candle is the one that opens at or after the start_time
#                 - Include pre-market and after-hours data and no easy way to exclude (https://forum.alpaca.markets/t/premarket-data-in-python/14012/6)
#                 - Last bar is always the one that closes after the end_time. 
#                 - If start_time and end_time are within the same candle (start after candle open and end before candle close), then no candle is returned

# Some examples of get_stock_bars behavior:
# start = 19:59:00, end = 20:01:00, timeframe = 1min: single candle from 19:59:00 to 20:00:00
# start = 19:59:00, end = 20:01:00, timeframe = 5min: no candle returned
# start = 19:59:00, end = 19:59:59, timeframe = 1min: single candle from 19:59:00 to 20:00:00
# start = 14:59:00, end = 14:59:59, timeframe = 1min: single candle from 14:59:00 to 15:00:00. If end = 15:00:00, then same candle and one sbusequent candle are returned
# start = 14:55:01, end = 14:59:59, timeframe = 5min: no candle is returned
# start = 13:30:00, end = 13:35:00, timeframe = 1min; 6 candles returned, first 13:30, last 13:35
# getCalendarOpenCloseTime returns the beginning of the actual bar whereas Alpaca takes calendar dates (for example, if first trading day of a month is 3rd then requesting monthly candle from 3rd of that month will return next month candle)
# More implmementation details:
#   High TF (higher than D): a) get complete candles (up to the candle that closes before or on end_time);
#                            b) build the last partial candle out of D candles (up to a candle that closes before or on end_time);
#                            c) build the last D candle out of 1min bars from market open to end_time
#   Daily TF: do steps a) and c)
#   Intraday TF: do steps a) and c)
# Note: we need to pull one extra candle prior to the sequence so as to identify whether the first candle is 1, 2, or 3
    def getChart(self, symbol_list, timeframe_sym, start_timestamp, end_timestamp):
        #self._get_db()  # Ensure the DB is initialized
        EST = 'America/New_York'
        PST = "America/Los_Angeles"

        if timeframe_sym[0] == 'm' and timeframe_sym[1:].isdigit():
            intraday = True
        else:
            intraday = False

        start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz=EST)
        end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz=EST)
        # Get the beginning of the candle prior to the one corresponding to start_timestamp:
        #   If start_timestamp is before candle open and after previous close (outside of market hours) --> need to pull one previous candle to get previous low and high
        #   If start_timestamp is after candle open and before candle close (falls within candle range) --> previous low and high are defined by the most recent previous candle
        #   So either way we need to pull one previous candle
        # Note: MarketTimeManager always ignores premarket and afterhours times, so below will correctly return previous candle for all timeframes (including intraday)
        start_time_query = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=start_timestamp, timeframe_sym=timeframe_sym, n_pre=1, n_post=0)
        start_time_query = start_time_query['pre'][0]
        start_time_query = start_time_query[0]

        # Identify timespan of the last partial candle
        end_time_query = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym=timeframe_sym, n_pre=1, n_post=0)
        # Get the end of the last complete candle
        end_time_complete_candle = end_time_query['pre'][0][1]
        
        # Get complete candles.  
        #request_params = StockBarsRequest(symbol_or_symbols=symbol_list, timeframe=tf, start=start_time_query, end=end_time_complete_candle)
        #bars = self.getChartWithPrintout(request_params=request_params)
        # Hourly TF is constructed from 30min bars because Alpaca agreggates from top of the hour (so 6:00, 7:00, etc instead of 6:30, 7:30 etc).
        # We pull 30min bars here and aggregate to hourly TF later
        # Note that previous candle is pulled correctly since it uses start_time_query calculated using 60min TF
        if timeframe_sym == 'm60':
            candleList_open = self.market_time_manager.getCandleList(timeframe='m30', start_time=start_time_query.timestamp(), end_time=end_time_complete_candle.timestamp())[0]
            bars = self.getBarsByOpenTS(symbol_or_symbols=symbol_list, timeframe='m30', open_ts=candleList_open)
        else:
            candleList_open = self.market_time_manager.getCandleList(timeframe=timeframe_sym, start_time=start_time_query.timestamp(), end_time=end_time_complete_candle.timestamp())[0]
            bars = self.getBarsByOpenTS(symbol_or_symbols=symbol_list, timeframe=timeframe_sym, open_ts=candleList_open)
        #if not bars.empty:  # check if complete candles exist - for tickers that went IPO recently and (especially) high TFs we may not have enough history
            #bars.drop(columns=['volume', 'trade_count', 'vwap'], inplace=True)
        #    if not intraday:    # TODO: this is a hack due to Alpaca returning 0:00:00 UTC time for D and higher TFs. Need to find a better way
        #        bars.index = pd.MultiIndex.from_arrays(
        #        [bars.index.get_level_values('symbol'), 
        #            bars.index.get_level_values('timestamp').map(lambda x: x.tz_convert(EST).replace(hour=9, minute=30, second=0))], 
        #            names=['symbol', 'timestamp'])

        # If end_time_query['current'] is None or end_time_query['current'] opens less than a minute from end_time (partial candle is <1min long), then there is no partial candle and we are done
        # If end_time_query['current'] is not None, then we have a partial candle, which starts at end_time_query['current'][0] 
        # If high timeframe (higher than D) - find complete D candles of the partial candle
        bars_daily = None
        bars_1min = None
        bars_partial = None
        if end_time_query['current'] is not None and end_time_query['current'][0] <= end_time - pd.DateOffset(minutes=1):   # need to build the last partial candle
            #last_daily_candle_end = None
            last_daily_candle_query = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym='d', n_pre=1, n_post=0)
            last_daily_candle_end = last_daily_candle_query['pre'][0][1]
            last_daily_candle_start = last_daily_candle_query['pre'][0][0]  # complete (not open) daily candle
            partial_candle = end_time_query['current']
            # Check if there are complete daily candles within partial candle
            # If intraday: partial candle is shorter than day and complete daily candle cannot start after the open of that partial candle
            # If daily: partial candle is after complete candle
            # If larger TF: partial candle open is the same as a daily candle open. If partial candle does not contain complete daily candles 
            # then it will open after the last complete daily candle
            if last_daily_candle_start >= partial_candle[0]:    # there are complete daily candles within the partial candle
                candleList_open = self.market_time_manager.getCandleList(timeframe="d", start_time=partial_candle[0].timestamp(), end_time=last_daily_candle_end.timestamp())[0]
                bars_daily = self.getBarsByOpenTS(symbol_or_symbols=symbol_list, timeframe="d", open_ts=candleList_open)
                partial_candle = last_daily_candle_query['current']
            #if not (intraday or timeframe_sym == 'd'):    
            #    last_daily_candle_end = last_daily_candle_query['pre'][0][1]
            #    if last_daily_candle_end > end_time_complete_candle:    # there are complete daily candles within the partial candle
            #        candleList_open = self.market_time_manager.getCandleList(timeframe="d", start_time=end_time_query['current'][0].timestamp(), end_time=last_daily_candle_end.timestamp())[0]
            #        bars_daily = self.getBarsByOpenTS(symbol_or_symbols=symbol_list, timeframe="d", open_ts=candleList_open)
            last_1min_candle_query = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym='m1', n_pre=1, n_post=0)
            
            # partial_candle_start can be None if high TF and end_time is outside of market D. In this case, there is no partial candle to build from 1min bars
            if (not partial_candle is None) and partial_candle[0] <= end_time-pd.DateOffset(minutes=1):  # need to get 1min bars only if there is at least one full 1min bar to get (otherwise Alpaca returns error)
                candleList_open = self.market_time_manager.getCandleList(timeframe="m1", start_time=partial_candle[0].timestamp(), end_time=end_time.timestamp())[0]
                bars_1min = self.getBarsByOpenTS(symbol_or_symbols=symbol_list, timeframe="m1", open_ts=candleList_open)
            
            # Compile the last partial candle
            if intraday or timeframe_sym == 'd':    # partial candle is built entirely from 1min bars
                if bars_1min is not None:
                    bars_partial = self.aggregateChart(bars_1min, timeframe_symbol=timeframe_sym)
            else:   # partial candle is built from complete D bars and 1min bars
                if bars_1min is not None:
                    bars_partial = self.aggregateChart(bars_1min, timeframe_symbol='d')
                if bars_daily is not None:
                    bars_partial = pd.concat([bars_daily, bars_partial]).sort_index()
                bars_partial = self.aggregateChart(bars_partial, timeframe_symbol=timeframe_sym)
        
        if bars_partial is not None:
            # Add bars_last to bars
            if not bars.empty:
                bars = pd.concat([bars, bars_partial]).sort_index()
            else:
                bars = bars_partial
        if intraday and not bars.empty:
            # For intraday, Alpaca includes candles outside of market hours, so we need to drop those
            day_count = int((end_timestamp - start_timestamp)/(24*60*60)) + 3    # to ensure we include partial days corresponding to start and end timestamps. #TODO: how many days to add?
            candle_ranges = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp+24*60*60, timeframe_sym='d', n_pre=day_count, n_post=0)
            candle_ranges = candle_ranges['pre'] 
            bars = bars[bars.index.get_level_values('timestamp').to_series().apply(lambda ts: any(start_dt <= ts < end_dt for start_dt, end_dt in candle_ranges)).values]
            bars = self.aggregateChart(bars, timeframe_symbol=timeframe_sym)

        '''
        # , otherwise - find the beginning and end of the partial candle
        # In case of intraday, end_time_query['current'][0] is accurate beginning of the partial candle; end_timestamp is accurate end of the partial candle
        # In case of higher TF (D, W, M, Q, Y), end_time_query['current'][0] is accurate beginning of the partial candle and matches the beginning of the first D candle comprising higher TF partial candle;
        #   if end_time is on trading day before market opens or on non-trading day then partial candle ends at the close of the previous D candle
        #   if end_time is on trading day after market close, then partial candle ends at the close of the current D candle
        #   if end_time is on trading day during market hours, then partial candle needs to be built from the close of the previous D candle and using 1min bars of the current day until end_time
        #   Therefore, end_time is always built from the end of previous D candle and if end_time is within market hours - from 1min bars of current day
        bars_last = None
        bars_1min = None
        if end_time_query['current'] is not None:   # need to find the timespan of partial candle. Note: for high TF (W, M, Q, Y), end_timestamp may fall on non-trading day while being within the partial candle 
            # Two step process: 
            # - If end_time is within market hours, then get the last partial daily candle from 1min bars; 
            # - For TF higher than D, get complete D candles comprising the partial candle and then add the last partial D candle from previous step

            end_time_daily = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym='d', n_pre=1, n_post=0)
            # If end_time is during market hours and is at least 1min after open, build last D partial candle from 1min bars
            if (end_time_daily['current'] is not None) and (end_time_daily['current'][0] <= end_time-pd.DateOffset(minutes=1)):   
                # Always pull 1min bars starting from market open to get proper aggregation
                request_params = StockBarsRequest(symbol_or_symbols=symbol_list, timeframe=TimeFrame.Minute, start=end_time_daily['current'][0], end=end_time-pd.DateOffset(minutes=1))
                bars_1min = self.getChartWithPrintout(request_params=request_params)
                #request_counter = 5
                #while request_counter > 0:
                #    try:
                #        bars_1min = stock_client.get_stock_bars(request_params)
                #        break
                #    except Exception as e:
                #        with lock:
                #            print(f"Error retrieving bars. Error: {e}")
                #            request_counter -= 1
                #            if request_counter == 0:
                #                raise e
                #            print(f"Retrying in 1min... ({5 - request_counter}/5)")
                #        time.sleep(60)
                #bars_1min = bars_1min.df
                #bars_1min.reset_index('symbol', inplace=True)
                if intraday:
                    bars_1min = self.aggregateChart(bars_1min, timeframe_symbol=timeframe_sym)
                    # drop bars before start_time_query. Note that if start_time_query is within the first candle, then the first candle needs to be retained
                    bars_todrop = bars_1min[bars_1min.index.get_level_values("timestamp") <= start_time_query]
                    if not bars_todrop.empty:  
                        bars_1min = pd.concat([bars_todrop.iloc[[-1]], bars_1min[bars_1min.index.get_level_values("timestamp") > start_time_query]])
                else:
                    bars_1min = self.aggregateChart(bars_1min, timeframe_symbol='d')
            end_time_daily = end_time_daily['pre'][0]
            if end_time_complete_candle < end_time_daily[1]:   # there are complete daily candles to add to partial candle (this block can only execute for higher TF)
                if intraday:
                    print("Something is wrong, executing block that should not execute for intraday")
                request_params = StockBarsRequest(symbol_or_symbols=symbol_list, timeframe=TimeFrame.Day, start=end_time_complete_candle, end=end_time_daily[1])
                bars_last = self.getChartWithPrintout(request_params=request_params)
                #request_counter = 5
                #while request_counter > 0:
                #    try:
                #        bars_last = stock_client.get_stock_bars(request_params)
                #        break
                #    except Exception as e:
                #        print(f"Error retrieving bars, will wait for 1min. Error: {e}")
                #        request_counter -= 1
                #        time.sleep(60)
                #        if request_counter == 0:
                #            raise e
                #        print(f"Retrying... ({5 - request_counter}/5)")
                #bars_last = bars_last.df
                #bars_last.reset_index('symbol', inplace=True)
                if bars_1min is not None:
                    bars_last = pd.concat([bars_last, bars_1min]).sort_index()
                bars_last = self.aggregateChart(bars_last, timeframe_symbol=timeframe_sym)
            else:
                bars_last = bars_1min

        if timeframe_sym == 'd':
            start_time_query = start_time_query.replace(hour=0, minute=0, second=0)
            tf = TimeFrame.Day
        elif timeframe_sym == 'w':
            start_time_query = start_time_query-pd.Timedelta(days=start_time_query.weekday())
            start_time_query = start_time_query.replace(hour=0, minute=0, second=0)
            tf = TimeFrame.Week
        elif timeframe_sym == 'm':
            start_time_query = start_time_query.replace(day=1, hour=0, minute=0, second=0)
            tf = TimeFrame.Month
        elif timeframe_sym == 'q':
            start_time_query = start_time_query.replace(day=1, hour=0, minute=0, second=0) # the month when Q candle actually opens is always the first month of that quarter  
            tf = TimeFrame(3, TimeFrameUnit.Month)
        elif timeframe_sym == 'y':
            start_time_query = start_time_query.replace(day=1, hour=0, minute=0, second=0) # the month when Y candle actually opens is always the first month of that year
            tf = TimeFrame(12, TimeFrameUnit.Month)
        #new_method = 1
        #if not new_method:
        #    request_params = StockBarsRequest(symbol_or_symbols=symbol_list, timeframe=TimeFrame.Day, start=start_time_query, end=end_time)
        #   bars = stock_client.get_stock_bars(request_params)
        #    bars = bars.df
        #    bars.reset_index('symbol', inplace=True)
        #    bars = aggregateChart(bars, timeframe_symbol=timeframe_sym)
        #else:
        # Alternative method (should be faster) - get complete candles and only build the last candle if it is partial
        # Complete candles.  
        request_params = StockBarsRequest(symbol_or_symbols=symbol_list, timeframe=tf, start=start_time_query, end=end_time_complete_candle)
        bars = self.getChartWithPrintout(request_params=request_params)
        #request_counter = 5
        #while request_counter > 0:
        #    try:
        #        bars = stock_client.get_stock_bars(request_params)
        #        break
        #    except Exception as e:
        #        print(f"Error retrieving bars, will wait for 1min. Error: {e}")
        #        request_counter -= 1
        #        time.sleep(60)
        #        if request_counter == 0:
        #            raise e
        #        print(f"Retrying... ({5 - request_counter}/5)")
        #bars = bars.df
        #bars.reset_index('symbol', inplace=True)
        if not bars.empty:  # check if complete candles exist - for tickers that went IPO recently and (especially) high TFs we may not have enough history
            bars.drop(columns=['volume', 'trade_count', 'vwap'], inplace=True)
            if not intraday:    # TODO: this is a hack due to Alpaca returning 0:00:00 UTC time for D and higher TFs. Need to find a better way
                bars.index = pd.MultiIndex.from_arrays(
                [bars.index.get_level_values('symbol'), 
                    bars.index.get_level_values('timestamp').map(lambda x: x.tz_convert(EST).replace(hour=9, minute=30, second=0))], 
                    names=['symbol', 'timestamp'])
                #bars.index = bars.index.map(lambda x: x.tz_convert(EST).replace(hour=9, minute=30, second=0)) # TODO: this is a hack due to Alpaca returning 0:00:00 UTC time for D and higher TFs. Need to find a better way
            
        # Last partial candle
        if bars_last is not None:
            # Add bars_last to bars
            bars = pd.concat([bars, bars_last]).sort_index()
        if intraday:
            # For intraday, Alpaca includes candles outside of market hours, so we need to drop those
            day_count = int((end_timestamp - start_timestamp)/(24*60*60)) + 3    # to ensure we include partial days corresponding to start and end timestamps. #TODO: how many days to add?
            candle_ranges = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp+24*60*60, timeframe_sym='d', n_pre=day_count, n_post=0)
            candle_ranges = candle_ranges['pre'] 
            bars = bars[bars.index.get_level_values('timestamp').to_series().apply(lambda ts: any(start_dt <= ts < end_dt for start_dt, end_dt in candle_ranges)).values]
            bars = self.aggregateChart(bars, timeframe_symbol=timeframe_sym)
            #if compositeHourTF:
                # Aggregate bars into composite hour TF. Note: correct first 30min candle is guaranteed by MarketTimeManager
            #    resample_period = str(int(tf_minute_count/60)) + 'h'
            #    bars.index = bars.index - pd.Timedelta(minutes=30) # TODO: this assumes that market always opens at xx:30:00; ideally need to confirm using market calendar or something
            #   bars = bars.resample(resample_period, label='left').apply(aggregate_barsDF).dropna()
            #    bars['timestamp'] = bars['timestamp'] + pd.Timedelta(minutes=30)
            #    bars.set_index('timestamp', inplace=True)
        '''
        candles = {}
        if not bars.empty:
            bars.drop(columns=['volume', 'trade_count', 'vwap'], inplace=True, errors='ignore')
            symbol_list = bars.index.get_level_values('symbol').unique()
            for sym in symbol_list:
                bars_sym = bars.xs(sym, level='symbol')
                if bars_sym.index[0].date() > start_time_query.date():   # This mean we don't have enough history, do not discard the first candle
                    logger.warning(f"Warning: no candle opening at {start_time_query} returned for {sym}")
                    previousCandleHigh = None
                    previousCandleLow = None
                    firstCandleToReport = 0
                else:
                    previousCandleHigh = bars_sym.iloc[0].high
                    previousCandleLow = bars_sym.iloc[0].low
                    firstCandleToReport = 1
                candles[sym] = self.convertBarsToCandleList(bars_sym[firstCandleToReport:], previousCandleHigh, previousCandleLow)
        return candles


# Convert daily chart into higher TF. Supported timeframes: W, M, Q, Y. Returns Panda DataFrame.
# NOTE: requires daily chart to start at the beginning of the HTF period, otherwise the first HTF will be incorrect (wrong open, and possibly wrong high and low)
#def aggregateDailyChart(barsDataFrame, timeframe_symbol):
#    barsDataFrame_HTF = barsDataFrame.resample(aggregation_resample_dict[timeframe_symbol], label='left').apply(aggregate_barsDF)#.asfreq('D')
#    barsDataFrame_HTF.set_index('timestamp', inplace=True)
#    barsDataFrame_HTF.dropna(how='all', inplace=True)
#    return barsDataFrame_HTF

# Convert chart into higher TF. Supported timeframes: "mxxx" where xxx is the number of minutes and 'd' (for the entire day to be built from 1min candles). Returns Panda DataFrame.
    def aggregateChart(self, barsDataFrame, timeframe_symbol):
        tf = None
        offset_needed = False   # this is to handle the case when we need to shift the barsDataFrame by 30min to get the correct first candle (due to flip being at the bottom of the hour)
        if timeframe_symbol in self.aggregation_resample_dict:
            tf = self.aggregation_resample_dict[timeframe_symbol]
        elif int(timeframe_symbol[1:]) < 60:
            tf = timeframe_symbol[1:]+"min"
        else:
            tf = str(int(int(timeframe_symbol[1:])/60)) + 'h'
            offset_needed = True
            barsDataFrame.index = pd.MultiIndex.from_arrays(
                [barsDataFrame.index.get_level_values('symbol'), 
                barsDataFrame.index.get_level_values('timestamp') - pd.Timedelta(minutes=30)], 
                names=['symbol', 'timestamp'])
        #barsDataFrame_HTF = barsDataFrame.resample(tf, label='left').apply(aggregate_barsDF).dropna()
        # Apply resampling within each symbol group
        barsDataFrame_HTF = (
            barsDataFrame.groupby(level="symbol")  # Group by "symbol"
            .apply(lambda g: g.resample(tf, level="timestamp", label="left").apply(self.aggregate_barsDF))  # Resample within each symbol
        )
        barsDataFrame_HTF.index = pd.MultiIndex.from_arrays(
            [barsDataFrame_HTF.index.get_level_values('symbol'), 
            barsDataFrame_HTF['timestamp']], 
            names=['symbol', 'timestamp'])
        barsDataFrame_HTF.drop(columns=['timestamp'], inplace=True)
        # Ensure the first timestamp in each bin is set as the new index
        #barsDataFrame_HTF = barsDataFrame_HTF.set_index("timestamp", append=True)
        if offset_needed:
            barsDataFrame_HTF.index = pd.MultiIndex.from_arrays(
                [barsDataFrame_HTF.index.get_level_values('symbol'), 
                barsDataFrame_HTF.index.get_level_values('timestamp') + pd.Timedelta(minutes=30)], 
                names=['symbol', 'timestamp'])
            
        barsDataFrame_HTF.dropna(how='all', inplace=True)
        return barsDataFrame_HTF

    # This function converts BarSet returned by get_stock_bars into a list of Candles instances
    def convertBarsToCandleList(self, bars, previousHigh, previousLow):
        if not bars.empty: # check if we got any bars
            bars_prev = bars.shift(1)
            bars_prev.iat[0, bars_prev.columns.get_loc('high')] = previousHigh
            bars_prev.iat[0, bars_prev.columns.get_loc('low')] = previousLow
            convertedData = bars.apply(lambda row: candles.Candle(row.name.timestamp()*1000, row.open, row.high, row.low, row.close, bars_prev.loc[row.name, 'high'].item(), bars_prev.loc[row.name, 'low'].item()), axis=1).to_list()
            return convertedData
        else:   # this should never execute
            return []


    # Get daily chart - this is used for all HTF charts. Returns Alpaca Bars object. Per Alpaca docs (https://forum.alpaca.markets/t/help-with-barset/3372/2), Bars are guaranteed to be in ascending order
    # Note: Python wrapper for Alpaca handles large number of returned bars behind the scenes (applies pagination and such)
    # Returns bars as Panda Dataframe
    #def getDailyChart(self, stock_client, symbol, start_timestamp, end_timestamp):
    #    start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz='America/New_York')
    #    end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz='America/New_York')
    #    start_time = start_time.replace(hour=0, minute=0, second=0)
    #    request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start_time, end=end_time, limit=10000)
    #    bars = stock_client.get_stock_bars(request_params)
    #    bars = bars.df
    #    bars.reset_index('symbol', inplace=True)
    #    return bars

    def printChart(self, chart, filename):
        with open(filename, 'a') as f:
            for sym in chart.keys():
                f.write('Symbol: ' + sym + '\n')
                for candle in chart[sym]:
                    f.write(candle.to_string_full() + '\n')

    def getBarsByOpenTS(
        self, 
        symbol_or_symbols: Union[str, List[str]], 
        timeframe: str, 
        open_ts: list[pd.Timestamp], 
    ) -> pd.DataFrame:
        """
        Fetch bars for given symbols, timeframe, and open timestamps. Note - if timestamp is not a valid open timestamp for a given timeframe, no errors are reported 
        Returns panda DataFrame
        Implementation details:
        1. Check which candles are already in the DB
        2. For missing candles - fetch from Alpaca and insert into DB
        3. Return combined DataFrame of candles found in DB and those fetched from Alpaca

            df_found: DataFrame indexed by (symbol, timestamp) with candles found in DB
            missing_dict: {symbol: list of open_ts missing in DB}

        Hybrid approach:
        - If total rows < max_values_rows -> use VALUES() query
        - Otherwise -> use TEMP TABLE with batched inserts

        Alpaca sets opening of D and higher TF candles to 0:00:00 UTC (and day = 1 for M, Q, Y) regardless of actual market open time. 
        When fetching Alpaca candles, those timestamps will be converted to actual candle open time 
        """
        EST = 'America/New_York'
        if timeframe == 'm60':
            logger.error("Timeframe 'm60' is not supported in getBarsByOpenTS. Use 'm30' instead and aggregate to hourly TF if needed.")
            raise ValueError("Timeframe 'm60' is not supported in getBarsByOpenTS. Use 'm30' instead and aggregate to hourly TF if needed.")
        symbols = symbol_or_symbols if isinstance(symbol_or_symbols, List) else [symbol_or_symbols]

        # Convert open_ts to Alpaca-friendly timestamps for D and higher TFs
        #if timeframe in ['d', 'w']:
        #    open_ts = [ts.tz_convert(EST).replace(hour=0, minute=0, second=0) for ts in open_ts]
        #elif timeframe in ['m', 'q', 'y']:
        #    open_ts = [ts.tz_convert(EST).replace(day=1, hour=0, minute=0, second=0) for ts in open_ts]
        open_ts = sorted(open_ts)
        missing_dict = {s: [] for s in symbols}
        try:
            df_found = self.db.get_candles_by_open_timestamp(
                symbol_or_symbols=symbols, 
                timeframe=timeframe, 
                open_ts=open_ts
            )
            # Compute missing timestamps per symbol and find the range covering all missing timestamps
            start_ts = None
            end_ts = None
            for sym in symbols:
                if df_found.empty or sym not in df_found.index.levels[0]:
                    missing_dict[sym] = open_ts
                else:
                    present_ts = set(df_found.loc[sym].index)
                    missing_dict[sym] = [ts for ts in open_ts if ts not in present_ts]
                start_ts_sym = min(missing_dict[sym]) if missing_dict[sym] else None
                start_ts = start_ts_sym if start_ts is None else min(start_ts, start_ts_sym) if start_ts_sym is not None else start_ts
                end_ts_sym = max(missing_dict[sym]) if missing_dict[sym] else None
                end_ts = end_ts_sym if end_ts is None else max(end_ts, end_ts_sym) if end_ts_sym is not None else end_ts

            # Remove any candles with open=0 (dummy candles inserted to DB to prevent re-fetching). Need to ensure to do that after computing missing timestamps
            df_found = df_found[df_found['open'] != 0]  

            # Fetch missing candles from Alpaca if any
            if start_ts is not None and end_ts is not None: # there are missing candles to fetch
                fetch_timestamp = pd.Timestamp.now(tz=EST)    # conservative timestamp - if candle closes after this timestamp, assume last fetched candle is live
                # Fetch missing candles from Alpaca               
                # Note: end_ts is open timestamp of the last candle we need to fetch. Alpaca returns that candle even if end_ts is exactly on candle open time
                df_fetched = self.alpaca_fetch(symbols=symbols, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)  
                # Process fetched DataFrame
                if not df_fetched.empty:
                    if list(df_fetched.index.names) != ['symbol', 'timestamp']:
                        df_fetched = df_fetched.reset_index().set_index(['symbol', 'timestamp'])

                    #if not intraday:    # TODO: this is a hack due to Alpaca returning 0:00:00 UTC time for D and higher TFs. Need to find a better way
                    #    df_fetched.index = pd.MultiIndex.from_arrays(
                    #    [df_fetched.index.get_level_values('symbol'), 
                    #        df_fetched.index.get_level_values('timestamp').map(lambda x: x.tz_convert(EST).replace(hour=9, minute=30, second=0))], 
                    #        names=['symbol', 'timestamp'])

                    if not df_found.empty:
                        df_result = pd.concat([df_found, df_fetched]).sort_index()
                        df_result = df_result[~df_result.index.duplicated(keep="first")]
                    else:
                        df_result = df_fetched
                    
                    # Remove live candle if present from what was fetched and insert fetched candles into DB
                    last_fetched_candle = self.market_time_manager.getCandleOpenCloseTime(timestamp_s = end_ts.timestamp(), timeframe_sym=timeframe, n_pre=0, n_post=0)
                    if last_fetched_candle['current'] and last_fetched_candle['current'][1] > fetch_timestamp:
                        df_fetched = df_fetched[df_fetched.index.get_level_values('timestamp') < last_fetched_candle['current'][0]]      
                    self.db.insert_candles(timeframe, df_fetched)
                else:
                    df_result = df_found
                # Sometimes Alpaca (and other brokerages) misses candles (mainly on 1min timeframe) - need to add dummy candles for missing timestamps to insert into DB (to prevent re-fetching those candles repeatedly)
                for sym in symbols:
                    if not df_fetched.empty and sym in df_fetched.index.get_level_values('symbol'):
                        fetched_ts = set(df_fetched.loc[sym].index)
                    else:
                        fetched_ts = set()
                    missing_after_fetch = [ts for ts in missing_dict[sym] if ts not in fetched_ts]
                    if missing_after_fetch:
                        logger.debug(f"""After fetching from Alpaca, still missing {len(missing_after_fetch)} candles for {sym} on timeframe {timeframe}. Inserting dummy candles to DB to prevent re-fetching.
                                            Missing timestamps range from {min(missing_after_fetch)} to {max(missing_after_fetch)}""")
                        df_dummy = pd.DataFrame(index=pd.MultiIndex.from_product([[sym], missing_after_fetch], names=['symbol', 'timestamp']), columns=['open', 'high', 'low', 'close'])
                        df_dummy[['open', 'high', 'low', 'close', 'volume', 'trade_count', 'vwap']] = 0.0
                        self.db.insert_candles(timeframe, df_dummy)
            else:
                df_result = df_found
        except Exception as e:
            logger.error(f"Error retrieving bars. Error: {e}")
            raise e
        return df_result
        
    
    def alpaca_fetch(self, symbols: List[str], timeframe: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
        """ Fetches stock bars from Alpaca, handling retries and missing ranges. 
        First candle is the one that contains start_ts (opens at start_ts or opens before and closes after start_ts); if start_ts is outside of candle, then candle immediately after start_ts is returned 
        Last candle is the one that either contains end_ts (opens at end_ts or opens before and closes after end_ts). If end_ts is outside of candle, then candle immediately before end_ts is returned.
        Main use case is in conjunction with getBarsByOpenTS where start_ts and end_ts are open timestamps of the first and the last candles to fetch respectively.
        """
        EST = 'America/New_York'
        request_counter = self.MAX_REQUESTS
        intraday = False

        if timeframe == 'd':
            tf = TimeFrame.Day
            start_ts = start_ts.replace(hour=0, minute=0, second=0) # Alpaca returns next candle if time is not set to 0:00:00 for D and higher TFs 
        elif timeframe == 'w':
            tf = TimeFrame.Week
            start_ts = start_ts-pd.Timedelta(days=start_ts.weekday())
            start_ts = start_ts.replace(hour=0, minute=0, second=0)
        elif timeframe == 'm':
            tf = TimeFrame.Month
            start_ts = start_ts.replace(day=1, hour=0, minute=0, second=0)
        elif timeframe == 'q':
            tf = TimeFrame(3, TimeFrameUnit.Month)
            quarterStartMonth = 3*((start_ts.month-1)//3)+1
            start_ts = start_ts.replace(month=quarterStartMonth, day=1, hour=0, minute=0, second=0) 
        elif timeframe == 'y':
            tf = TimeFrame(12, TimeFrameUnit.Month)
            start_ts = start_ts.replace(month=1, day=1, hour=0, minute=0, second=0)
        elif timeframe[0] == 'm' and timeframe[1:].isdigit():
            intraday = True
            tf_minute_count = int(timeframe[1:])
            tf = TimeFrame(tf_minute_count, TimeFrameUnit.Minute)
        else:
            logger.error(f"Unsupported timeframe symbol: {timeframe}")
            raise ValueError(f"Unsupported timeframe symbol: {timeframe}")
        if not intraday:
            start_ts = start_ts.replace(hour=0, minute=0, second=0) # Alpaca returns next candle if time is not set to 0:00:00 for D and higher TFs 
        request_params = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=tf,
            start=start_ts,
            end=end_ts,   # even if end_ts is exactly on candle open time, that candle is still returned by Alpaca
            adjustment='split',
        )        
        while request_counter > 0:
            try:
                if not self.rate_limiter is None:
                    self.rate_limiter.acquire()  # Wait for rate limit slot
                logger.debug(f"Fetching bars for {request_params.symbol_or_symbols} from {request_params.start.tz_localize('UTC').tz_convert(EST)} to {request_params.end.tz_localize('UTC').tz_convert(EST)} with timeframe {request_params.timeframe}")
                bars = self.session.get_stock_bars(request_params)
                break
            except Exception as e:
                request_counter -= 1
                if request_counter == 0:
                    logger.error(f"Error retrieving bars. Error: {e} - giving up after {self.MAX_REQUESTS} attempts.")
                    raise e
                else:
                    logger.info(f"Error retrieving bars. Error: {e} - retrying in 1min... ({5 - request_counter}/5)")
                time.sleep(60)
        bars = bars.df
        if bars.empty:
            logger.warning(f"Warning: no bars returned from Alpaca, symbol(s): {symbols}, timeframe: {timeframe}, start: {start_ts}, end: {end_ts}")
            return bars
        # For intraday, Alpaca includes candles outside of market hours, so we need to remove those
        if intraday:
            try:
                day_count = int((end_ts.timestamp() - start_ts.timestamp())/(24*60*60)) + 3    # to ensure we include partial days corresponding to start and end timestamps. #TODO: how many days to add?
                candle_ranges = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_ts.timestamp()+24*60*60, timeframe_sym='d', n_pre=day_count, n_post=0)
                candle_ranges = candle_ranges['pre'] 
                bars = bars[bars.index.get_level_values('timestamp').to_series().apply(lambda ts: any(start_dt <= ts < end_dt for start_dt, end_dt in candle_ranges)).values]
                bars.index = bars.index.remove_unused_levels()
            except Exception as e:
                logger.error(f"Error dropping candles outside of market hours. Error: {e}")
                raise e
        # Update timestamps (specifically for D and higher TFs). Alpaca sets opening of D and higher TF candles to 0:00:00 UTC (and day = 1 for M, Q, Y) regardless of actual market open time.
        try:
            bars.index = bars.index.set_levels(bars.index.get_level_values("timestamp").unique().map(lambda ts: self.getProperCandleOpen(timeframe, ts)), level="timestamp")
        except Exception as e:
            logger.error(f"Error updating candle open timestamps. Error: {e}")
            raise e

        return bars
    
    def getProperCandleOpen(self, timeframe_symbol: str, timestamp: pd.Timestamp) -> pd.Timestamp:
        """
        Given a timeframe symbol and a timestamp reported by Alpaca, return the proper candle open time for that timeframe.
        Implementation details:
        - For intraday timeframes, Alpaca always reports the correct candle open time
        - For D and higher timeframes, Alpaca reports candle open time as 0:00:00 UTC of the day (and day=1 for M, Q, Y) regardless of actual market open time
        - Therefore, for D and higher timeframes, we need to use MarketTimeManager to find the open time of the next candle after the reported timestamp
        """
        timestamp_dict = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=timestamp.timestamp(), timeframe_sym=timeframe_symbol, n_pre=0, n_post=1)
        if not timestamp_dict['current'] is None:
            return timestamp_dict['current'][0]
        else:
            return timestamp_dict['post'][0][0]
        
        
# -------------------------------
# Sample Worker Function
# -------------------------------
def backtest_symbol(symbol, market_time_manager, time_frame, startTS, endTS):
    dr = DataRetrieval(shared_limiter, market_time_manager=market_time_manager, db_path="chartDB_test.db")
    if isinstance(symbol, str):
        symbol = [symbol]
    data = dr.getChart(symbol_list=symbol, timeframe_sym=time_frame, start_timestamp=startTS, end_timestamp=endTS)
    return data

# -------------------------------
# Main
# -------------------------------
if __name__ == "__main__":
    symbols = ['AAPL', 'GOOG', 'NFLX']#, 'MSFT', 'TSLA', 'NVDA', 'AMZN', 'NFLX', 'META']
    EST = 'America/New_York'
    pd.options.mode.copy_on_write = True
    #session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    time_manager = mtm.MarketTimeManager()
    #session = DataRetrieval(market_time_manager=time_manager)
    startDay = pd.to_datetime("2025-02-18 10:15:00").tz_localize(EST)
    endDay = pd.to_datetime("2025-02-18 12:58:00").tz_localize(EST)
    print(f"Requesting data from {startDay} to {endDay}")
    #watchlist = pd.read_csv('Watchlists/test_wl.csv', header = None)
    #watchlist = watchlist[0].to_list()
    #watchlist = ['IWM']
    #chart = session.get_stock_bars(StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=startDay, end=endDay))
    #chart = chart.df
    #print(chart)

    file_path = "chartDB_test.db"

    if os.path.exists(file_path):
        os.remove(file_path)
    
    with mp.Manager() as manager:
        limiter = SharedRateLimiter(manager)

        #with mp.Pool(processes=4, initializer=init_pool, initargs=(limiter,)) as pool:
        #    chart_list = pool.starmap(backtest_symbol, 
        #                         [(symbol, time_manager, 'm60', startDay.timestamp(), endDay.timestamp()) for symbol in symbols]
        #                        )  
        #os.remove(file_path) 
        #chart_single = backtest_symbol(symbols, time_manager, 'm60', startDay.timestamp(), endDay.timestamp())
                                  
    '''
    print('Hourly chart: ')
    for ticker in chart_single.keys():
        print('Symbol: ' + ticker)
        for candle in chart_single[ticker]:
            print(candle.to_string_full())

    print('Hourly chart from multiprocessing: ')
    for chart in chart_list:
        for ticker in chart.keys():
            print('Symbol: ' + ticker)
            for candle in chart[ticker]:
                print(candle.to_string_full())
    '''

    #os.remove(file_path)
    dr = DataRetrieval(rate_limiter=None, market_time_manager=time_manager, db_path="chartDB_test.db")
    chart_no_limit = dr.getChart(symbol_list=symbols, timeframe_sym='m1', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())

    print('Hourly chart from DataRetrieval with no rate limit: ')
    for ticker in chart_no_limit.keys():
        print('Symbol: ' + ticker)
        for candle in chart_no_limit[ticker]:
            print(candle.to_string_full())
    
    print("\nSummary after first request:")
    dr.db.summary("NFLX")
    print("\n")

    print("Adding 5min")
    startDay = startDay + pd.Timedelta(minutes=5)
    endDay = endDay + pd.Timedelta(minutes=5)
    chart_no_limit = dr.getChart(symbol_list=symbols, timeframe_sym='m1', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Hourly chart from DataRetrieval with no rate limit with extra 5min in the end: ')
    for ticker in chart_no_limit.keys():
        print('Symbol: ' + ticker)
        for candle in chart_no_limit[ticker]:
            print(candle.to_string_full())
    
    print("\nSummary after second request:")
    dr.db.summary("NFLX")

    '''
    chart = session.getChart(symbol_list=watchlist, timeframe_sym='m60', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Hourly chart: ')
    for ticker in chart.keys():
        print('Symbol: ' + ticker)
        for candle in chart[ticker]:
            print(candle.to_string_full())

    chart = session.getChart(symbol_list=watchlist, timeframe_sym='d', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Daily chart: ')
    for ticker in chart.keys():
        print('Symbol: ' + ticker)
        for candle in chart[ticker]:
            print(candle.to_string_full())
    
    chart = session.getChart(symbol_list=watchlist, timeframe_sym='w', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Weekly chart: ')
    for ticker in chart.keys():
        print('Symbol: ' + ticker)
        for candle in chart[ticker]:
            print(candle.to_string_full())

    chart = session.getChart(symbol_list=watchlist, timeframe_sym='m', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Monthly chart: ')
    for ticker in chart.keys():
        print('Symbol: ' + ticker)
        for candle in chart[ticker]:
            print(candle.to_string_full())

    chart = session.getChart(symbol_list=watchlist, timeframe_sym='q', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Quarterly chart: ')
    for ticker in chart.keys():
        print('Symbol: ' + ticker)
        for candle in chart[ticker]:
            print(candle.to_string_full())

    chart = session.getChart(symbol_list=watchlist, timeframe_sym='y', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    print('Yearly chart: ')
    for ticker in chart.keys():
        print('Symbol: ' + ticker)
        for candle in chart[ticker]:
            print(candle.to_string_full())
    '''
    # see: https://forum.alpaca.markets/t/how-to-get-bars-within-30-mins-time-frame/11613
    
    # DASH open price on March 19 2025 - TV shows 185.23 (intraday), 186 (Daily). 186.27 reported - matches TOS intraday chart


    #Warning: Not enough candles in d timeframe to record combo for GOOGL on 2025-05-01 09:30:00-04:00. Reduced combo recording.
    #Warning: Not enough candles in d timeframe to record combo for FAST on 2025-05-01 09:30:00-04:00. Reduced combo recording.
    #Warning: Not enough candles in d timeframe to record combo for BKR on 2025-05-01 09:30:00-04:00. Reduced combo recording.