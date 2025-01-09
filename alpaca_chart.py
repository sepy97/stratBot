from alpaca.data import StockHistoricalDataClient
from datetime import datetime
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca_config import alpaca_config
import pandas as pd
import candles
#import util
import MarketTimeManager as mtm

aggregation_resample_dict = {'w': 'W', 'm': 'ME', 'q': 'Q', 'y': 'YE'}

# This function creates a single OHLC dataframe record from a series of smaller TF dataframes (assuming all smaller TF dataframes are for the same symbol)
def aggregate_barsDF(df):
        return pd.Series({
            'symbol': df['symbol'].iloc[0],
            'open': df['open'].iloc[0],
            'high': df['high'].max(),
            'low': df['low'].min(),
            'close': df['close'].iloc[-1],
        })

def initSession():
    stock_client = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    return stock_client

# Returns a list of candles. 
# First candle in the list is the one that closes after start_timestamp and previous candle closes before start_timestamp 
# If start_timestamp falls within the candle (candle open is before and candle close is after the timestamp), then that candle is the first one in the returned series.
# Last candle always respects end_timestamp time (i.e. produces partial candle is end_timestamp falls in-between open and close time of a candle). If end_timestamp does not have time provided, time is set to 0:0:0
#
# Implementation detail:
# get_stock_bars: in Daily and higher timeframes, if start_time does not specify the time (only date) or if the time is 00:00:00EST then the first candle is the one that opens on the date of start_time, 
#                 otherwise it is the candle that opens next  
#                 Last bar always corresponds to the date of the end_time in EST
# getCalendarOpenCloseTime returns the beginning of the actual bar whereas Alpaca takes calendar dates (for example, if first trading day of a month is 3rd then requesting monthly candle from 3rd of that month will return next month candle)
# Note: we need to pull one extra candle prior to the sequence so as to identify whether the first candle is 1, 2, or 3
def getChart(stock_client, symbol, timeframe_sym, start_timestamp, end_timestamp):
    EST = 'America/New_York'
    PST = "America/Los_Angeles"

    start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz=EST)
    end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz=EST)
    # Get the beginning of the candle prior to the one corresponding to start_timestamp:
    #   If start_timestamp is before candle open and after previous close (outside of market hours) --> need to pull one previous candle to get previous low and high
    #   If start_timestamp is after candle open and before candle close (falls within candle range) --> previous low and high are defined by first previous candle
    start_time_query = mtm.getCandleOpenCloseTime(timestamp_s=start_timestamp, timeframe_sym=timeframe_sym, n_pre=1, n_post=0)
    start_time_query = start_time_query['pre'][0]
    start_time_query = start_time_query[0]

    # Identify timespan of the last partial candle
    partial_candle = None
    end_time_query = mtm.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym=timeframe_sym, n_pre=1, n_post=0)
    
    if end_time_query['current'] is not None:   # need to find the timespan of partial candle. TODO: currently does not work for intraday
        previous_candle = end_time_query['pre'][0] 
        end_time_daily = mtm.getCandleOpenCloseTime(timestamp_s=end_timestamp, timeframe_sym='d', n_pre=0, n_post=1)
        next_daily_candle = end_time_daily['post'][0]
        if (end_time_daily['current'] is None) and (end_time.date() == next_daily_candle[0].date()):   # end time stamp before market hours
            partial_candle = (previous_candle[1], end_time - pd.DateOffset(days=1))   # from close of previous candle to close of current candle
        else:
            partial_candle = (previous_candle[1], end_time)
    end_time_query = end_time_query['pre'][0]
    end_time_query = end_time_query[1]

    '''
    TODO: support intraday timeframes
    if timeframe_sym == 'm1':
        bars = stock_client.get_stock_bars(StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start_time, end=end_time))
        bars = bars.df
        bars.reset_index('symbol', inplace=True)
    '''
    tf = None
    if timeframe_sym == 'd':
        start_time_query = start_time_query.replace(hour=0, min=0, second=0)
        tf = TimeFrame.Day
    elif timeframe_sym == 'w':
        start_time_query = start_time_query-pd.Timedelta(days=startDay.weekday())
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
    new_method = 1
    if not new_method:
        request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start_time_query, end=end_time)
        bars = stock_client.get_stock_bars(request_params)
        bars = bars.df
        bars.reset_index('symbol', inplace=True)
        bars = aggregateDailyChart(bars, timeframe_symbol=timeframe_sym)
        previousCandleHigh = bars.iloc[0].high
        previousCandleLow = bars.iloc[0].low
        candles = convertBarsToCandleList(bars[1:], previousCandleHigh, previousCandleLow)
    else:
        # Alternative method (should be faster) - get complete candles and only build the last candle if it is partial
        # Complete candles
        request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start_time_query, end=end_time_query)
        bars = stock_client.get_stock_bars(request_params)
        bars = bars.df
        bars.reset_index('symbol', inplace=True)
        bars.drop(columns=['volume', 'trade_count', 'vwap'], inplace=True)
        # Last partial candle
        if partial_candle is not None:
            request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=partial_candle[0], end=partial_candle[1])
            bars_last = stock_client.get_stock_bars(request_params)
            bars_last = bars_last.df
            bars_last.reset_index('symbol', inplace=True)
            bars_last = aggregateDailyChart(bars_last, timeframe_symbol=timeframe_sym)
            # Add bars_last to bars
            bars = pd.concat([bars, bars_last])
        previousCandleHigh = bars.iloc[0].high
        previousCandleLow = bars.iloc[0].low
        candles = convertBarsToCandleList(bars[1:], previousCandleHigh, previousCandleLow)
    
    return candles


# Convert daily chart into higher TF. Supported timeframes: W, M, Q, Y. Returns Panda DataFrame.
# NOTE: requires daily chart to start at the beginning of the HTF period, otherwise the first HTF will be incorrect (wrong open, and possibly wrong high and low)
def aggregateDailyChart(barsDataFrame, timeframe_symbol):
    barsDataFrame['timestamp'] = pd.to_datetime(barsDataFrame.index)
    barsDataFrame.set_index('timestamp', inplace=True)
    barsDataFrame_HTF = barsDataFrame.resample(aggregation_resample_dict[timeframe_symbol], label='left').apply(aggregate_barsDF).asfreq('D')
    barsDataFrame_HTF.dropna(how='all', inplace=True)
    return barsDataFrame_HTF

# This function converts BarSet returned by get_stock_bars into a list of Candles instances
def convertBarsToCandleList(bars, previousHigh, previousLow):
    if not bars.empty: # check if we got any bars
        bars_prev = bars.shift(1)
        bars_prev.iat[0, bars_prev.columns.get_loc('high')] = previousHigh
        bars_prev.iloc[0, bars_prev.columns.get_loc('low')] = previousLow
        convertedData = bars.apply(lambda row: candles.Candle(row.name.timestamp()*1000, row.open, row.high, row.low, row.close, bars_prev.loc[row.name, 'high'].item(), bars_prev.loc[row.name, 'low'].item()), axis=1).to_list()
        return convertedData
    else:   # this should never execute
        return []


# Get daily chart - this is used for all HTF charts. Returns Alpaca Bars object. Per Alpaca docs (https://forum.alpaca.markets/t/help-with-barset/3372/2), Bars are guaranteed to be in ascending order
# Returns bars as Panda Dataframe
def getDailyChart(stock_client, symbol, start_timestamp, end_timestamp):
    start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz='America/New_York')
    end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz='America/New_York')
    start_time = start_time.replace(hour=0, minute=0, second=0)
    request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start_time, end=end_time, limit=10000)
    bars = stock_client.get_stock_bars(request_params)
    bars = bars.df
    bars.reset_index('symbol', inplace=True)
    return bars

if __name__ == "__main__":
    EST = 'America/New_York'
    pd.options.mode.copy_on_write = True
    session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    startDay = pd.to_datetime("2024-10-01 0:00:00").tz_localize(EST)
    endDay = pd.to_datetime("2024-10-15 0:00:00").tz_localize(EST)
    chart = getChart(session, symbol="SPY", timeframe_sym='w', start_timestamp=startDay.timestamp(), end_timestamp=endDay.timestamp())
    for candle in chart:
        print(candle.to_string_full())

    #start_time_query = mtm.getCandleOpenCloseTime(timestamp_s=startDay, timeframe_sym='d', n_pre=1, n_post=0)
    #start_time_query = start_time_query['pre'][0]
    #start_time_query = start_time_query[0]
    #print('Date specified: ' + str(startDay))
    #print('Date to start query: ' + str(start_time_query.tz_convert(EST)))

    #bars.reset_index('symbol', inplace=True)
    #barsDF = getDailyChart(session, 'SPY', startDay.timestamp(), endDay.timestamp())

    #candleList = convertBarsToCandleList(bars.iloc[1:], bars.iloc[0].high, bars.iloc[0].low)
    #print(candleList)
    #barsDF_M = aggregateDailyChart(barsDF, 'w')
    #print(barsDF_M)
    #candles = getChart(session, "SPY", 'm', startDay.timestamp(), endDay.timestamp())
    #print(candles)
    
    #tf2 = TimeFrame(15, TimeFrameUnit.Minute)
    #print(tf2)
    # see: https://forum.alpaca.markets/t/how-to-get-bars-within-30-mins-time-frame/11613
