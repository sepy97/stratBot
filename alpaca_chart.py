from alpaca.data import StockHistoricalDataClient
from datetime import datetime
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca_config import alpaca_config
import pandas as pd

def initSession():
    stock_client = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    return stock_client

# Returns a list of candles.
# In Daily timeframe, if start_time does not specify the time (only date) or if the time is 00:00:00EST then the first candle is the one that opens on the date of start_time, 
# otherwise it is the candle that opens the next trading day. Last bar corresponds to the date of the end_time in EST
# 
def getChart(stock_client, symbol, timeframe_sym, start_timestamp, end_timestamp):
    EST = 'America/New_York'
    PST = "America/Los_Angeles"
    if timeframe_sym == 'm1':
        tf = TimeFrame.Minute
    if timeframe_sym == 'd':
        tf = TimeFrame.Day
    
    #start_time = datetime.utcfromtimestamp(start_timestamp)
    #end_time = datetime.utcfromtimestamp(end_timestamp)
    start_time = pd.Timestamp.fromtimestamp(start_timestamp, tz=EST)
    end_time = pd.Timestamp.fromtimestamp(end_timestamp, tz=EST)
    request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start_time, end=end_time)
    bars = stock_client.get_stock_bars(request_params)
    chart = []
    for b in bars.data[symbol]:
        candle = {'open': b.open, \
                  'high': b.high, \
                  'low': b.low, \
                  'close': b.close, \
                  'datetime': datetime.timestamp(b.timestamp)}
        chart.append(candle)
    return chart

if __name__ == "__main__":
    EST = 'America/New_York'
    session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    startDay = pd.to_datetime("2024-11-19 0:00:00").tz_localize(EST)
    endDay = pd.to_datetime("2024-11-22 0:00:00").tz_localize(EST)
    candles = getChart(session, "SPY", 'd', startDay.timestamp(), endDay.timestamp())
    print(candles)
    
    #tf2 = TimeFrame(15, TimeFrameUnit.Minute)
    #print(tf2)
    # see: https://forum.alpaca.markets/t/how-to-get-bars-within-30-mins-time-frame/11613
