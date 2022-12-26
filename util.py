#import datetime

#utc_date_str = '2022-05-26 00:00:00'
#dt = datetime.datetime.strptime(utc_date_str, '%Y-%m-%d %H:%M:%S')

#epoch = datetime.datetime.utcfromtimestamp(0)
#print((dt - epoch).total_seconds())

import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import tomlkit
from pathlib import Path

from enum import Enum

# dictionary where for each timeframe we have a tuple with (timeframe_LUT, period_type, frequency_type, frequency)
# TODO: add yearly back into LUT
#timeframe_LUT = {'y': (365*24*60*60*1000, "year", "yearly", 1), 'q': (91*24*60*60*1000, "year", "monthly", 1), 'm': (30*24*60*60*1000, "year", "monthly", 1), 'w': (7*24*60*60*1000, "month", "weekly", 1), 'd': (24*60*60*1000, "month", "daily", 1), 'm60': (60*60*1000, "day", "minute", 30), 'm30': (30*60*1000, "day", "minute", 30), 'm15': (15*60*1000, "day", "minute", 15), 'm5': (5*60*1000, "day", "minute", 5)}
timeframe_LUT = {'q': (91*24*60*60*1000, "year", "monthly", 1), 'm': (30*24*60*60*1000, "year", "monthly", 1), 'w': (7*24*60*60*1000, "month", "weekly", 1), 'd': (24*60*60*1000, "month", "daily", 1), 'm60': (60*60*1000, "day", "minute", 30), 'm30': (30*60*1000, "day", "minute", 30), 'm15': (15*60*1000, "day", "minute", 15), 'm5': (5*60*1000, "day", "minute", 5)}
timeframe_LUT = {'y': (365*24*60*60*1000, "year", "yearly", 1), 'q': (91*24*60*60*1000, "year", "monthly", 1), 'm': (30*24*60*60*1000, "year", "monthly", 1), 'w': (7*24*60*60*1000, "month", "weekly", 1), 'd': (24*60*60*1000, "month", "daily", 1), 'm60': (60*60*1000, "day", "minute", 30), 'm30': (30*60*1000, "day", "minute", 30), 'm15': (15*60*1000, "day", "minute", 15), 'm5': (5*60*1000, "day", "minute", 5)}

class TickerStatus(Enum):
    OUT = 1
    LONG = 2
    SHORT = 3

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

def getStartOf3Candles(endTime_ms, timeframe):
    # Get period of time required to cover 4 candles worth of data for given timeframe ending at specific endTime  
    #    (3 latest candles to form pattern, 1 candle before these 3 to provide previous high/low)
    # 3 quarterly candles and 3 monthly candles can be contained within 1 year
    # 3 weekly candles and 3 daily candles require 1 month of data 
    # All intraday timeframes require data starting previous trading day
    endTime = datetime.fromtimestamp(endTime_ms/1000)
    if timeframe == "y":
        startTime = endTime.replace(year=endTime.year-3, month=1, day=1)
    if (timeframe == "q"):
        quarterEndMonth = 3*((endTime.month-1)//3+1)
        startTime = endTime.replace(year=endTime.year-1, month=quarterEndMonth)
        startTime = (startTime + timedelta(days=32)).replace(day=1) #first day of period of time exactly a year before the end of quarter
    if (timeframe == "m"):
        currentMonth = endTime.month
        if currentMonth > 3:
            startTime = endTime.replace(month=currentMonth-3, day=1)
        else:
            startTime = endTime.replace(year=endTime.year-1, month=currentMonth+12-3, day=1)
    if (timeframe == "w") or (timeframe == "d"):
        startTime = endTime - timedelta(days=32)
    if (timeframe == "m60") or (timeframe == "m30") or (timeframe == "m15") or (timeframe == "m5"): #TODO: clean up to reduce the amount of data to last trading day only
        nyse = mcal.get_calendar('NYSE')
        prevDay = getPreviousTradingDay(endTime)
        sch = nyse.schedule(datetime.fromtimestamp(prevDay/1000).date(), datetime.fromtimestamp(prevDay/1000).date())
        startTime = sch.iloc[-1]['market_open']
    startTime = int(startTime.timestamp()*1000)
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
    # Note - if timestamp is equal to market close then return false 
    marketOpenClose = getOpenCloseAtDay(timestamp_ms)
    return (marketOpenClose["open"] <= timestamp_ms) and (marketOpenClose["close"] > timestamp_ms)
    
def getCandleChange_ms(timestamp_ms, timeframe):
    # At all timeframes:
    #    candleEndTimeStamp_ms- return timestamp of close of candle  containing 'timestamp_ms' if it is within market hours, or close of most recent candle
    #    nextCandleStartTimeStamp_ms - return timestamp of open of next candle 
    # Candle starts at xx:xx:00 time, and ends at xx:xx:59 time (e.g. first m15 in the regular trading day ends at 6:44:59 PST). All microseconds are reset to 0
    # For Y, Q, W - return market close timestamp minus 1sec for day corresponding to end of corresponding macro-period 
    # For D - return market close timestamp minus 1 sec of the most recent trading day 
    # For intraday:
    #    If timestamp_ms is outside trading hours - return most recent market close timestamp 
    #    If timestamp_ms is within trading hours then find integer k such that: t_open + k*p <= timestamp_ms < t_open + (k+1)*p 
    #        where t_open is market open time at the day, p is corresponding period (60min for m60, 15min for m15, etc)
    #        k = floor((timestamp_ms - t_open)/p) but since timestamp_ms > t_open we can do int((timestamp_ms - t_open)/p)
    #        Close of candle is (initially) t_open + (k+1)*p
    #        If close of candle outside of trading hours then return market close minus 1sec

    # Implementation details:
    #     If timestamp is during trading day before market open, market scheduler includes that day - needs to be removed manually
    #     Assume that there is at least one trading day over 7 day period (used in large timeframes)
    #     For large time frames (D and larger): detect end of calendar period (year, quarter, month, week, day) containing timestamp, then get daily schedule for the last 7 days
    #     For instraday - find timestamps and compare against open and close time of the day

    timestampDate = datetime.fromtimestamp(timestamp_ms/1000)
    nyse = mcal.get_calendar('NYSE')
    schedule = nyse.schedule(start_date=str(timestampDate), end_date=str(timestampDate))
    candleEndTimeStamp_ms = None
    nextCandleStartTimeStamp_ms = None
    periodEndDate = None
    if (not schedule.empty) and (timestamp_ms < 1000*schedule.iloc[-1]['market_open'].timestamp()):  # before market open on a trading day - ignore this day
        timestampDate = timestampDate - timedelta(days=1)

    # intraday
    if (timeframe=="m60") or (timeframe=="m30") or (timeframe=="m15") or (timeframe=="m5"):
        if (not schedule.empty) and (timestamp_ms >= 1000*schedule.iloc[-1]['market_open'].timestamp()) and (timestamp_ms < 1000*schedule.iloc[-1]['market_close'].timestamp()):  #timestamp_ms is inside trading hours
            period = timeframe_LUT[timeframe][0]
            openTime_ms = 1000*schedule.iloc[-1]['market_open'].timestamp()
            closeTime_ms = 1000*schedule.iloc[-1]['market_close'].timestamp()
            k = int((timestamp_ms - openTime_ms)/period)
            periodEndTimestamp_ms = openTime_ms + (k+1)*period
            candleEndTimeStamp_ms = min(periodEndTimestamp_ms, closeTime_ms)-1000
            if candleEndTimeStamp_ms + 1000 >= closeTime_ms:
                periodEndDate = datetime.fromtimestamp(closeTime_ms/1000)
                scheduleNextPeriod = nyse.schedule(start_date=str(periodEndDate+timedelta(days=1)), end_date=str(periodEndDate+timedelta(days=7)))
                nextCandleStartTimeStamp_ms = int(1000*scheduleNextPeriod.iloc[0]['market_open'].timestamp())
            else:
                nextCandleStartTimeStamp_ms = candleEndTimeStamp_ms + 1000
            return candleEndTimeStamp_ms, nextCandleStartTimeStamp_ms

        else:      #timestamp_ms is outside of market hours
            periodEndDate = timestampDate

    # yearly 
    if timeframe=="y":
        periodEndDate = timestampDate.replace(year=timestampDate.year+1, month=1, day=1)-timedelta(days=1)
    # quarterly
    if timeframe=="q":
        quarterEndMonth = 3*((timestampDate.month-1)//3+1)
        periodEndDate = (timestampDate.replace(month=quarterEndMonth, day=1) + timedelta(days=32)).replace(day=1, hour=23, minute=59, second=59, microsecond=0) - timedelta(days=1)
    # monthly 
    if timeframe=="m":
        periodEndDate = (timestampDate.replace(day=1) + timedelta(days=32)).replace(day=1, hour=23, minute=59, second=59, microsecond=0) - timedelta(days=1)
    # weekly
    if timeframe=="w":
        weekEndDate = timestampDate - timedelta(timestampDate.weekday()) + timedelta(days=6)
        periodEndDate = weekEndDate.replace(hour=23, minute=59, second=59, microsecond=0)
    # daily
    if timeframe=="d":
        periodEndDate = timestampDate

    periodStartDate = periodEndDate - timedelta(days=7)
    schedule = nyse.schedule(start_date=str(periodStartDate), end_date=str(periodEndDate))
    candleEndTimeStamp_ms = int(1000*(schedule.iloc[-1]['market_close']-timedelta(seconds=1)).timestamp())
    scheduleNextPeriod = nyse.schedule(start_date=str(schedule.iloc[-1]['market_close']+timedelta(days=1)), end_date=str(schedule.iloc[-1]['market_close']+timedelta(days=7)))
    nextCandleStartTimeStamp_ms = int(1000*scheduleNextPeriod.iloc[0]['market_open'].timestamp())
    return candleEndTimeStamp_ms, nextCandleStartTimeStamp_ms

def loadSymbols():
    symbols = []

    dic = tomlkit.loads(Path("config.toml").read_text())
    for element in dic["watchlist"]:
        symbols.append(element["symbol"])
    return symbols