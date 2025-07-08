from alpaca.data import StockHistoricalDataClient
from datetime import datetime
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca_config import alpaca_config
import pandas as pd
import candles
import time
import multiprocessing as mp
import MarketTimeManager as mtm

class DataRetrieval:
    #_lock = None
    #_manager = None
    def __init__(self, market_time_manager=None):
        self.session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
        if market_time_manager is None:
            self.market_time_manager = mtm.MarketTimeManager()
        else:
            self.market_time_manager = market_time_manager
        #self.manager = mp.Manager()
        #self._lock = lock
        #if DataRetrieval._lock is None:
        #    DataRetrieval._manager = Manager()
        #    DataRetrieval._lock = DataRetrieval._manager.Lock()
        #    print("[DEBUG] Lock initialized")
        self.MAX_REQUESTS = 5
        self.aggregation_resample_dict = {'d': 'D', 'w': 'W', 'm': 'ME', 'q': 'QE', 'y': 'YE'}
#aggregation_resample_dict = {'d': 'D', 'w': 'W', 'm': 'ME', 'q': 'QE', 'y': 'YE'}
#    @classmethod
#    def initDataRetrieval(cls):
#        manager = Manager()
#        instance = cls(lock=manager.Lock())
#        instance._manager = manager
#        return instance
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

#def initSession():
#    stock_client = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
#    lock = mp.Lock()
#    return {'session': stock_client, 'mp_lock': lock}

# Returns a dictionary: {symbol --> [list of candles in chronological order (most recent candle last)]}
# First (oldest) candle in the list is the oldest candle that closes after start_timestamp (if start_timestamp is within the candle - it is the first candle; otherwise it is the next candle)
# Last (oldest) candle in the list opens before end_timestamp and closes on end_timestamp (could be partial candle)
# Supported TF: Y, Q, M, W, D, integer hours ('m60', 'm120', etc.), minutes ('m1', 'm5', 'm15', 'm30', etc.)
# start_timestamp and end_timestamp are in seconds
# Implementation detail:
# get_stock_bars: 
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
# getCalendarOpenCloseTime returns the beginning of the actual bar whereas Alpaca takes calendar dates (for example, if first trading day of a month is 3rd then requesting monthly candle from 3rd of that month will return next month candle)
# Note: we need to pull one extra candle prior to the sequence so as to identify whether the first candle is 1, 2, or 3
    def getChart(self, symbol_list, timeframe_sym, start_timestamp, end_timestamp):
        EST = 'America/New_York'
        PST = "America/Los_Angeles"
        intraday = False
        tf = None
        compositeHourTF = False # used to indicate that timeframe is in hours (m60, m120, etc.) which needs to be constructed from 30min bars
        if timeframe_sym[0] == 'm' and timeframe_sym[1:].isdigit():
            intraday = True
            tf_minute_count = int(timeframe_sym[1:])
            if tf_minute_count < 60:
                tf = TimeFrame(tf_minute_count, TimeFrameUnit.Minute)
            else:
                tf = TimeFrame(30, TimeFrameUnit.Minute)
                compositeHourTF = True
        start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz=EST)
        end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz=EST)
        # Get the beginning of the candle prior to the one corresponding to start_timestamp:
        #   If start_timestamp is before candle open and after previous close (outside of market hours) --> need to pull one previous candle to get previous low and high
        #   If start_timestamp is after candle open and before candle close (falls within candle range) --> previous low and high are defined by the most recent previous candle
        # Note: MarketTimeManager always ignores premarket and afterhours times, so below will correctly return previous candle for all timeframes (including intraday)
        start_time_query = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=start_timestamp, timeframe_sym=timeframe_sym, n_pre=1, n_post=0)
        start_time_query = start_time_query['pre'][0]
        start_time_query = start_time_query[0]

        # Identify timespan of the last partial candle
        end_time_query = self.market_time_manager.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym=timeframe_sym, n_pre=1, n_post=0)
        # Get the end of the last complete candle
        end_time_complete_candle = end_time_query['pre'][0]
        end_time_complete_candle = end_time_complete_candle[1]
        # If end_time_query['current'] is None, then there is no partial candle, otherwise - find the beginning and end of the partial candle
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
        candles = {}
        symbol_list = bars.index.get_level_values('symbol').unique()
        for sym in symbol_list:
            bars_sym = bars.xs(sym, level='symbol')
            if bars_sym.index[0].date() > start_time_query.date():   # TODO: this is a hack. Sometimes market calendar does not know of unexpected market closure (e.g. 2023-10-09)
                print(f"Warning: no candle opening at {start_time_query} returned for {sym}")
                previousCandleHigh = None
                previousCandleLow = None
            else:
                previousCandleHigh = bars_sym.iloc[0].high
                previousCandleLow = bars_sym.iloc[0].low
            candles[sym] = self.convertBarsToCandleList(bars_sym[1:], previousCandleHigh, previousCandleLow)
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
    def convertBarsToCandleList(sefl, bars, previousHigh, previousLow):
        if not bars.empty: # check if we got any bars
            bars_prev = bars.shift(1)
            bars_prev.iat[0, bars_prev.columns.get_loc('high')] = previousHigh
            bars_prev.iloc[0, bars_prev.columns.get_loc('low')] = previousLow
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

    def getChartWithPrintout(self, request_params):
        request_counter = self.MAX_REQUESTS
        while request_counter > 0:
            try:
                bars = self.session.get_stock_bars(request_params)
                break
            except Exception as e:
                #with self._lock:
                request_counter -= 1
                if request_counter == 0:
                    print(f"Error retrieving bars. Error: {e} - giving up after {self.MAX_REQUESTS} attempts.")
                    raise e
                else:
                    print(f"Error retrieving bars. Error: {e} - retrying in 1min... ({5 - request_counter}/5)")
                time.sleep(60)
        bars = bars.df
        return bars

if __name__ == "__main__":
    EST = 'America/New_York'
    pd.options.mode.copy_on_write = True
    #session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    time_manager = mtm.MarketTimeManager()
    session = DataRetrieval(market_time_manager=time_manager)
    startDay = pd.to_datetime("2025-04-15 9:29:00").tz_localize(EST)
    endDay = pd.to_datetime("2025-04-15 11:32:00").tz_localize(EST)
    watchlist = pd.read_csv('Watchlists/test_wl.csv', header = None)
    watchlist = watchlist[0].to_list()
    #chart = session.get_stock_bars(StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=startDay, end=endDay))
    #chart = chart.df
    #print(chart)

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
   
    # see: https://forum.alpaca.markets/t/how-to-get-bars-within-30-mins-time-frame/11613
    
    # DASH open price on March 19 2025 - TV shows 185.23 (intraday), 186 (Daily). 186.27 reported - matches TOS intraday chart