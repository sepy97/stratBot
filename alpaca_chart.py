from alpaca.data import StockHistoricalDataClient
from datetime import datetime
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca_config import alpaca_config
import pandas as pd
import candles

aggregation_resample_dict = {'w': 'W', 'm': 'ME', 'q': 'Q', 'y': 'A'}

# This function creates a single OHLC candle from a series of smaller TF candles
def aggregate_barsDF(df):
        return pd.Series({
            'open': df['open'].iloc[0],
            'high': df['high'].max(),
            'low': df['low'].min(),
            'close': df['close'].iloc[-1],
        })

def initSession():
    stock_client = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    return stock_client

# Returns a list of candles.
# Implementation detail:
# get_stock_bars: in Daily timeframe, if start_time does not specify the time (only date) or if the time is 00:00:00EST then the first candle is the one that opens on the date of start_time, 
#                 otherwise it is the candle that opens the next trading day. 
#                 Last bar always corresponds to the date of the end_time in EST
# This function does not make this distinction and ALWAYS returns the candle corresponding to start_date (regardless of time) as the first candle
# 
def getChart(stock_client, symbol, timeframe_sym, start_timestamp, end_timestamp):
    EST = 'America/New_York'
    PST = "America/Los_Angeles"
    start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz=EST)
    end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz=EST)
    if timeframe_sym == 'm1':
        bars = stock_client.get_stock_bars(StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start_time, end=end_time))
        bars = bars.df
        bars.reset_index('symbol', inplace=True)
    if timeframe_sym == 'd':
        bars = getDailyChart(symbol, start_timestamp, end_timestamp)
    if timeframe_sym == 'm':
        bars = getDailyChart(symbol, start_timestamp, end_timestamp)
        bars = aggregateDailyChart(bars, timeframe_sym)
    if timeframe_sym == 'w':
        bars = getDailyChart(symbol, start_timestamp, end_timestamp)
        bars = aggregateDailyChart(bars, timeframe_sym)

    candles = convertBarsToCandleList(bars, previousCandle)
    
    return chart
    
    #start_time = datetime.utcfromtimestamp(start_timestamp)
    #end_time = datetime.utcfromtimestamp(end_timestamp)

    #request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start_time, end=end_time)
    #bars = stock_client.get_stock_bars(request_params)
    #chart = []

# Convert daily chart into higher TF. Supported timeframes: W, M, Q, Y. Returns Panda DataFrame.
# NOTE: requires daily chart to start at the beginning of the HTF period, otherwise the first HTF will be incorrect (wrong open, and possibly wrong high and low)
def aggregateDailyChart(barsDataFrame, timeframe_symbol):
    # Build last candle
    # If M - build from daily candles
    # If Q - build last M from daily candles, and add other M of the Q if applicable
    #if timeframe_symbol == 'm':
        #start_time_lastMonth = end_time.replace(day=1, hour=0, minute=0, second=0)
        #end_time_lastMonth = end_time.replace(hour=0, minute=0, second=0)
        #request_params_lastMonth = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start_time_lastMonth, end=end_time_lastMonth)
        #lastMonth = stock_client.get_stock_bars(request_params_lastMonth)
        #lastMonth = lastMonth.df.loc[symbol]
        # Resample daily data into monthly data
    barsDataFrame['timestamp'] = pd.to_datetime(barsDataFrame.index)
    barsDataFrame.set_index('timestamp', inplace=True)
    barsDataFrame_HTF = barsDataFrame.resample(aggregation_resample_dict[timeframe_symbol]).apply(aggregate_barsDF).asfreq('D')
    barsDataFrame_HTF.dropna(how='all', inplace=True)
        #lastMonth_data = {'open': lastMonth_candle.iloc[0].open.item(), 
        #                  'high': lastMonth_candle.iloc[0].high.item(), 
        #                  'low': lastMonth_candle.iloc[0].low.item(), 
        #                  'close': lastMonth_candle.iloc[0].close.item(),
        #                  'datetime': datetime.timestamp(lastMonth.index[0])}
        #if len(chart) > 0:
        #    chart[-1] = lastMonth_data
        #else:
        #    chart.append(lastMonth_data)
    return barsDataFrame_HTF

# This function converts BarSet returned by get_stock_bars into a list of Candles instances
def convertBarsToCandleList(bars, previousHigh, previousLow):
    if not bars.empty: # check if we got any bars
        bars_prev = bars.shift(1)
        bars_prev.iloc[0].high = previousHigh
        bars_prev.iloc[0].low = previousLow
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
    request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start_time, end=end_time)
    bars = stock_client.get_stock_bars(request_params)
    bars = bars.df
    bars.reset_index('symbol', inplace=True)
    return bars

if __name__ == "__main__":
    EST = 'America/New_York'
    pd.options.mode.copy_on_write = True
    session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    startDay = pd.to_datetime("2024-09-02 0:00:00").tz_localize(EST)
    endDay = pd.to_datetime("2024-10-15 0:00:00").tz_localize(EST)
    barsDF = getDailyChart(session, 'SPY', startDay.timestamp(), endDay.timestamp())
    print(barsDF)
    candleList = convertBarsToCandleList(barsDF.iloc[1:], barsDF.iloc[0].high, barsDF.iloc[0].low)
    print(candleList)
    #barsDF_M = aggregateDailyChart(barsDF, 'w')
    #print(barsDF_M)
    #candles = getChart(session, "SPY", 'm', startDay.timestamp(), endDay.timestamp())
    #print(candles)
    
    #tf2 = TimeFrame(15, TimeFrameUnit.Minute)
    #print(tf2)
    # see: https://forum.alpaca.markets/t/how-to-get-bars-within-30-mins-time-frame/11613
