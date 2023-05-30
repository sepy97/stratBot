from alpaca.data import StockHistoricalDataClient
from datetime import datetime
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca_config import alpaca_config

def initSession():
    #stock_client = StockHistoricalDataClient("PKHLACDOGO2LLJ24TUAM", "MjdcWWVbbAcf4CFmFjUvRk7QbDmxpwnOYSOaRNW7")
    stock_client = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
    return stock_client

def getChart(stock_client, symbol, timeframe_sym, start_timestamp, end_timestamp):
    if timeframe_sym == 'm1':
        tf = TimeFrame.Minute
    if timeframe_sym == 'd':
        tf = TimeFrame.Day
    
    start_time = datetime.utcfromtimestamp(start_timestamp)
    end_time = datetime.utcfromtimestamp(end_timestamp)

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