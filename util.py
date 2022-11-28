#import datetime

#utc_date_str = '2022-05-26 00:00:00'
#dt = datetime.datetime.strptime(utc_date_str, '%Y-%m-%d %H:%M:%S')

#epoch = datetime.datetime.utcfromtimestamp(0)
#print((dt - epoch).total_seconds())

import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime
from dateutil.relativedelta import relativedelta

# dictionary where for each timeframe we have a tuple with (timeframe_LUT, period_type, frequency_type, frequency)
timeframe_LUT = {'y': (365*24*60*60*1000, "year", "yearly", 1), 'q': (91*24*60*60*1000, "year", "monthly", 1), 'm': (30*24*60*60*1000, "year", "monthly", 1), 'w': (7*24*60*60*1000, "month", "weekly", 1), 'd': (24*60*60*1000, "month", "daily", 1), 'm60': (60*60*1000, "day", "minute", 30), 'm30': (30*60*1000, "day", "minute", 30), 'm15': (15*60*1000, "day", "minute", 15), 'm5': (5*60*1000, "day", "minute", 5)}

#timestamp = 1545730073 # timestamp in seconds
#dt_obj = datetime.fromtimestamp(timestamp)
def getPreviousTradingDay(fromDay = None):
    # Get date of previous trading day as timestamp in ms, at time 00:00:00
    nyse = mcal.get_calendar('NYSE')
    if fromDay == None:
        fromDay = datetime.now()
    date = fromDay - pd.tseries.offsets.CustomBusinessDay(1, holidays = nyse.holidays().holidays)
    d = date.date()
    timestamp = datetime.strptime(str(d), '%Y-%m-%d').timestamp()
    return int(1000*timestamp)
def getTodayCloseTime_ms():
    nyse = mcal.get_calendar('NYSE')
    todayDataFrame = nyse.schedule(str(datetime.now().date()), str(datetime.now().date()))
    closeTime = todayDataFrame.iloc[-1]['market_close']
    return int(closeTime*1000)

def getStartOf3Candles(endTime, timeframe):
    # Get period of time required to cover 4 candles worth of data for given timeframe ending at specific endTime  
    #    (3 latest candles to form pattern, 1 candle before these 3 to provide previous high/low)
    # 3 quarterly candles and 3 monthly candles can be contained within 1 year
    # 3 weekly candles and 3 daily candles require 1 month of data 
    # All intraday timeframes require data starting previous trading day
    if (timeframe == "q") or (timeframe == "m"):
        startTime = endTime - relativedelta(years=1)
    if (timeframe == "w") or (timeframe == "d"):
        startTime = endTime - relativedelta(months=1)
    if (timeframe == "m60") or (timeframe == "m30") or (timeframe == "m15") or (timeframe == "m5"):
        nyse = mcal.get_calendar('NYSE')
        prevDay = getPreviousTradingDay(endTime)
        sch = nyse.schedule(datetime.fromtimestamp(prevDay/1000).date(), datetime.fromtimestamp(prevDay/1000).date())
        startTime = int(1000*sch.iloc[-1]['market_open'].timestamp())
        
    return startTime

def getOpenCloseAtDay(timestamp_ms):
    # Get open and close timestamps (in ms) at a day defined by timestamp_ms
    # Returns a dictionary with "open" and "close" fields. Both fields set to 0 if timestamp_ms falls on a non-trading day (weekend or holiday)
    nyse = mcal.get_calendar('NYSE')
    date = datetime.fromtimestamp(timestamp_ms/1000).date()
    schedule = nyse.schedule(start_date=str(date), end_date=str(date))
    result = {"open": 0, "close": 0}
    if not schedule.empty:
        closeTime = schedule.iloc[-1]['market_close']
        openTime = schedule.iloc[-1]['market_open']
        result["open"] = int(1000*openTime.timestamp())
        result["close"] = int(1000*closeTime.timestamp())
    return result
    
def isMarketOpen(timestamp_ms):
    marketOpenClose = getOpenCloseAtDay(timestamp_ms)
    return (marketOpenClose["open"] <= timestamp_ms) and (marketOpenClose["close"] >= timestamp_ms)
    
