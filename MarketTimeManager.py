from zoneinfo import ZoneInfo
import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime, timedelta, date
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest
from alpaca.trading.models import Calendar
from alpaca_config import alpaca_config
import pytz
from typing import List, Tuple, Dict, Any, cast
import logging

# dictionary where for each timeframe we have a tuple with (timeframe_LUT, period_type, frequency_type, frequency)
# TODO: add yearly back into LUT
logger = logging.getLogger(__name__)
SUPPORTED_TIMEFRAMES = ['y', 'q', 'm', 'w', 'd', 'm60', 'm30', 'm15', 'm5', 'm1']
timeframe_LUT = {'q': (91*24*60*60, "year", "monthly", 1), 'm': (30*24*60*60, "year", "monthly", 1), 'w': (7*24*60*60, "month", "weekly", 1), 'd': (24*60*60, "month", "daily", 1), 'm60': (60*60, "day", "minute", 30), 'm30': (30*60, "day", "minute", 30), 'm15': (15*60, "day", "minute", 15), 'm5': (5*60, "day", "minute", 5)}
class MarketTimeManager:
    def __init__(self):

        self.trading_client = TradingClient(alpaca_config['key'], alpaca_config['secret_key'])  # or paper=False for live
        self.tz = ZoneInfo("America/New_York")
        
        #tz = pytz.timezone('America/New_York')
        calendar = cast(List[Calendar], self.trading_client.get_calendar())
        self.calendar = pd.DataFrame([
            {
                'date': c.date,
                'market_open': c.open.replace(tzinfo=self.tz),
                'market_close': c.close.replace(tzinfo=self.tz)
            }
            for c in calendar
        ])

        self.calendar.index = self.calendar['date']
        #self.calendar = pd.DataFrame([{'date': c.date, 'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in calendar])
        #if dateRange is None:
        #    self.calendar_cache = None
        #else:
        #    cal = self.trading_client.get_calendar(GetCalendarRequest(start=pd.to_datetime(dateRange[0]).date(), end=pd.to_datetime(dateRange[1]).date()))
        #    self.calendar_cache = pd.DataFrame([{'date': tz.localize(c.date), 'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in cal])
        #calendar = trading_client.get_calendar(GetCalendarRequest(start=date(2026, 1, 5), end=date(2026, 1, 5))) this returns a list of dictionaries in a form
        #[{   'close': datetime.datetime(2026, 1, 5, 16, 0),
        #     'date': datetime.date(2026, 1, 5),
        #     'open': datetime.datetime(2026, 1, 5, 9, 30)}]

    def getPreviousTradingDay(self, fromDay = None):  #TODO: convert to use Alpaca client
        # Get date of previous trading day as timestamp in seconds, at time 00:00:00
        nyse = mcal.get_calendar('NYSE')
        if fromDay == None:
            fromDay = datetime.now()
        date = fromDay - pd.tseries.offsets.CustomBusinessDay(1, holidays = nyse.holidays().holidays)  # type: ignore[attr-defined]
        d = date.date()
        timestamp = datetime.strptime(str(d), '%Y-%m-%d').timestamp()
        return int(timestamp)
    def getTodayCloseTime(self): #TODO: convert to use Alpaca client
        nyse = mcal.get_calendar('NYSE')
        check_date = datetime.now().date()
        for _ in range(7):
            todayDataFrame = nyse.schedule(str(check_date), str(check_date))
            if not todayDataFrame.empty:
                closeTime = todayDataFrame.iloc[-1]['market_close']
                return int(closeTime.timestamp())
            check_date -= timedelta(days=1)
        raise RuntimeError("No trading day found in the last 7 days")
    def getTodayOpenTime(self):  #TODO: convert to use Alpaca client
        nyse = mcal.get_calendar('NYSE')
        check_date = datetime.now().date()
        for _ in range(7):
            todayDataFrame = nyse.schedule(str(check_date), str(check_date))
            if not todayDataFrame.empty:
                openTime = todayDataFrame.iloc[-1]['market_open']
                return int(openTime.timestamp())
            check_date -= timedelta(days=1)
        raise RuntimeError("No trading day found in the last 7 days")

    def getStartOf3Candles(self, endTime_s, timeframe):  #TODO: convert to use Alpaca client
        # Get period of time required to cover 4 candles worth of data for given timeframe ending at specific endTime  
        #    (3 latest candles to form pattern, 1 candle before these 3 to provide previous high/low)
        # 3 quarterly candles and 3 monthly candles can be contained within 1 year
        # 3 weekly candles and 3 daily candles require 1 month of data 
        # All intraday timeframes require data starting previous trading day
        endTime = datetime.fromtimestamp(endTime_s)
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
            prevDay = self.getPreviousTradingDay(endTime)
            sch = nyse.schedule(datetime.fromtimestamp(prevDay).date(), datetime.fromtimestamp(prevDay).date())
            startTime = sch.iloc[-1]['market_open']
        startTime = int(startTime.timestamp())
        return startTime

    def getOpenCloseAtDay(self, timestamp_s):    #TODO: convert to use Alpaca client
        # Get open and close timestamps (in seconds) at a day defined by timestamp_s
        # Returns a dictionary with "open" and "close" fields. Both fields set to 0 if timestamp_s falls on a non-trading day (weekend or holiday)
        nyse = mcal.get_calendar('NYSE')
        date = datetime.fromtimestamp(timestamp_s).date()
        schedule = nyse.schedule(start_date=str(date), end_date=str(date))
        result = {"open": 0, "close": 0}
        if not schedule.empty:
            closeTime = schedule.iloc[-1]['market_close']
            openTime = schedule.iloc[-1]['market_open']
            result["open"] = int(openTime.timestamp())
            result["close"] = int(closeTime.timestamp())
        return result
        
    def isMarketOpen(self, timestamp_s): #TODO: convert to use Alpaca client
        # Note - if timestamp is equal to market close then return false 
        marketOpenClose = self.getOpenCloseAtDay(timestamp_s)
        return (marketOpenClose["open"] <= timestamp_s) and (marketOpenClose["close"] > timestamp_s)
    
    def isMarketOpen(self, dt: datetime | int | float | None = None) -> bool:
        if dt is None:
            dt = datetime.now(self.tz)
        elif isinstance(dt, (int, float)):
            dt = datetime.fromtimestamp(dt, self.tz)
        else:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.tz)
            else:
                dt = dt.astimezone(self.tz)
        date = dt.date()

        # Not a trading day
        if date not in self.calendar.index:
            return False

        row = self.calendar.loc[date]

        return row['market_open'] <= dt <= row['market_close']
        
        #marketOpenClose = self.getOpenCloseAtDay(int(dt.timestamp()))
        #return (marketOpenClose["open"] <= int(dt.timestamp())) and (marketOpenClose["close"] > int(dt.timestamp()))
    def getCandleChange(self, timestamp_s, timeframe):  #TODO: convert to use Alpaca client
        # At all timeframes:
        #    candleEndTimeStamp_s - return timestamp of close of candle containing 'timestamp_s' if it is within market hours, or close of most recent candle
        #    nextCandleStartTimeStamp_s - return timestamp of open of next candle 
        # Candle starts at xx:xx:00 time, and ends at xx:xx:59 time (e.g. first m15 in the regular trading day ends at 6:44:59 PST). All microseconds are reset to 0
        # For Y, Q, W - return market close timestamp minus 1sec for day corresponding to end of corresponding macro-period 
        # For D - return market close timestamp minus 1 sec of the most recent trading day 
        # For intraday:
        #    If timestamp_s is outside trading hours - return most recent market close timestamp 
        #    If timestamp_s is within trading hours then find integer k such that: t_open + k*p <= timestamp_s < t_open + (k+1)*p 
        #        where t_open is market open time at the day, p is corresponding period (60min for m60, 15min for m15, etc)
        #        k = floor((timestamp_s - t_open)/p) but since timestamp_s > t_open we can do int((timestamp_s - t_open)/p)
        #        Close of candle is (initially) t_open + (k+1)*p
        #        If close of candle outside of trading hours then return market close minus 1sec

        # Implementation details:
        #     If timestamp is during trading day before market open, market scheduler includes that day - needs to be removed manually
        #     Assume that there is at least one trading day over 7 day period (used in large timeframes)
        #     For large time frames (D and larger): detect end of calendar period (year, quarter, month, week, day) containing timestamp, then get daily schedule for the last 7 days
        #     For instraday - find timestamps and compare against open and close time of the day

        timestampDate = datetime.fromtimestamp(timestamp_s)
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(start_date=str(timestampDate), end_date=str(timestampDate))
        candleEndTimeStamp_s = None
        nextCandleStartTimeStamp_s = None
        periodEndDate = None
        if (not schedule.empty) and (timestamp_s < schedule.iloc[-1]['market_open'].timestamp()):  # before market open on a trading day - ignore this day
            timestampDate = timestampDate - timedelta(days=1)

        # intraday
        if (timeframe=="m60") or (timeframe=="m30") or (timeframe=="m15") or (timeframe=="m5"):
            if (not schedule.empty) and (timestamp_s >= schedule.iloc[-1]['market_open'].timestamp()) and (timestamp_s < schedule.iloc[-1]['market_close'].timestamp()):  #timestamp_s is inside trading hours
                period = timeframe_LUT[timeframe][0]
                openTime_s = schedule.iloc[-1]['market_open'].timestamp()
                closeTime_s = schedule.iloc[-1]['market_close'].timestamp()
                k = int((timestamp_s - openTime_s)/period)
                periodEndTimestamp_s = openTime_s + (k+1)*period
                candleEndTimeStamp_s = min(periodEndTimestamp_s, closeTime_s)-1
                if candleEndTimeStamp_s + 1 >= closeTime_s:
                    periodEndDate = datetime.fromtimestamp(closeTime_s)
                    scheduleNextPeriod = nyse.schedule(start_date=str(periodEndDate+timedelta(days=1)), end_date=str(periodEndDate+timedelta(days=7)))
                    nextCandleStartTimeStamp_s = int(scheduleNextPeriod.iloc[0]['market_open'].timestamp())
                else:
                    nextCandleStartTimeStamp_s = candleEndTimeStamp_s + 1
                return candleEndTimeStamp_s, nextCandleStartTimeStamp_s

            else:      #timestamp_s is outside of market hours
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

        if periodEndDate is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        periodStartDate = periodEndDate - timedelta(days=7)
        schedule = nyse.schedule(start_date=str(periodStartDate), end_date=str(periodEndDate))
        candleEndTimeStamp_s = int((schedule.iloc[-1]['market_close']-timedelta(seconds=1)).timestamp())
        scheduleNextPeriod = nyse.schedule(start_date=str(schedule.iloc[-1]['market_close']+timedelta(days=1)), end_date=str(schedule.iloc[-1]['market_close']+timedelta(days=7)))
        nextCandleStartTimeStamp_s = int(scheduleNextPeriod.iloc[0]['market_open'].timestamp())
        return candleEndTimeStamp_s, nextCandleStartTimeStamp_s

    def detectTFFlip(self, current_time, TFperiod, time_quant): #TODO: convert to use Alpaca client
        #opening_time = getOpenCloseAtDay(int(current_time.timestamp()))["open"]
        opening_timestamp = self.getTodayOpenTime()
        current_timestamp = int(current_time.timestamp())
        delta = current_timestamp - opening_timestamp
        modulo = delta % TFperiod
        if modulo < time_quant:
            return True
        return False

    def getProperStartTime(self, current_time, time_quant): #TODO: convert to use Alpaca client
        # TODO: check for the day to be a trading day
        opening_time = self.getTodayOpenTime()
        delta = int(current_time.timestamp()) - opening_time
        proper_start_time = datetime.fromtimestamp(opening_time + (delta//time_quant + 1)*time_quant)
        return proper_start_time

    # Implementation details:
    #     Assume that there is at least one trading day over 7 day period (assumption used in large timeframes)
    #     For large time frames (W and larger): detect start and end of calendar period (year, quarter, month, week) containing timestamp, then get daily schedule for the 7 days after start and 7 days prior to end
    #     For daily and instraday same approach does not work because holidays can be larger than the entire calendar period of corresponding timeframe
    #     

    def getCandleOpenCloseTime(self, timestamp_s: int, timeframe_sym: str, n_pre: int =1, n_post: int =1, tz: str ='America/New_York') -> Dict[str, Any]:
        if not timeframe_sym in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {timeframe_sym}. Supported timeframes are: {SUPPORTED_TIMEFRAMES}")
        candleOpenCloseTime = {'pre': [], 'current': None, 'post': []}
        #nyse = mcal.get_calendar('NYSE')
        timestampDate = pd.to_datetime(timestamp_s, unit='s', utc=True).tz_convert('America/New_York')     # convert to Panda Datetime and ensure it is timezone-aware and in NY timezone
        if timestampDate.date() < self.calendar.index[0] or timestampDate.date() > self.calendar.index[-1]:  # timestamp is outside of the calendar range
            logger.error(f"Timestamp {timestampDate} is outside of the calendar range")
            return candleOpenCloseTime
        if timeframe_sym in ['m60', 'm30', 'm15', 'm5', 'm1']:
            period_s = int(timeframe_sym[1:])*60
            this_period_start = timestampDate.replace(hour=0, minute=0, second=0)
            this_period_end = timestampDate.replace(hour=23, minute=59, second=59)
            period_date = timestampDate.date()
            # populate current candle
            #sch_day = nyse.schedule(start_date=this_period_start, end_date=this_period_end)
            #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=this_period_start.date(), end=this_period_end.date()))
            #sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
            try:
                sch_day = self.calendar.loc[timestampDate.date()]
            except KeyError:
                sch_day = None
            if (not sch_day is None) and (timestampDate >= sch_day['market_open']) and (timestampDate < sch_day['market_close']-pd.DateOffset(seconds=1)):   # timestamp falls within the candle - populate current candle
                k = int((timestampDate - sch_day['market_open']).total_seconds()/period_s)  # number of candles prior to timestamp 
                candle_start = sch_day['market_open'] + pd.DateOffset(seconds=k*period_s)
                candle_end = min(sch_day['market_close'], sch_day['market_open'] + pd.DateOffset(seconds=(k+1)*period_s)) #- pd.DateOffset(seconds=1)
                candleOpenCloseTime['current'] = (candle_start, candle_end)
            # populate pre candles
            period_start = this_period_start
            period_end = this_period_end
            #sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
            #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=period_start.date(), end=period_end.date()))
            #sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
            try:
                sch_day = self.calendar.loc[timestampDate.date()]
            except KeyError:
                sch_day = None
            candles_collected = 0
            timestampAdj = timestampDate    # this timestamp is less than a period past the close of candle we need to add
            while candles_collected < n_pre:
                if sch_day is None or timestampAdj < sch_day['market_open'] + pd.DateOffset(seconds=period_s):   # timestamp falls on weekend/holiday or before open of the second candle of the day --> go to previous day
                    period_start = period_start - pd.DateOffset(days=1)
                    period_end = period_end - pd.DateOffset(days=1)
                    #sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
                    try:
                        sch_day = self.calendar.loc[period_start.date()]
                    except KeyError:    
                        sch_day = None
                    #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=period_start.date(), end=period_end.date()))
                    #sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                else:
                    timestampAdj = min(timestampAdj, sch_day['market_close'])   #timestamp after close --> shift to market close
                    k = int((timestampAdj - sch_day['market_open']).total_seconds()/period_s)
                    if (timestampAdj >= sch_day['market_close']) and (sch_day['market_open'] + pd.DateOffset(seconds=k*period_s) < sch_day['market_close']):    # account for situation when last candle of the day is partial (e.g. last 60min candle is only 30min long)
                        k = k + 1
                    candle_start = sch_day['market_open'] + pd.DateOffset(seconds=(k-1)*period_s)
                    candle_end = min(sch_day['market_close'], sch_day['market_open'] + pd.DateOffset(seconds=k*period_s)) #- pd.DateOffset(seconds=1)
                    candleOpenCloseTime['pre'].append((candle_start, candle_end))
                    timestampAdj = candle_start
                    candles_collected += 1
            
            # populate post candles
            period_start = this_period_start
            period_end = this_period_end
            #sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
            #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=period_start.date(), end=period_end.date()))
            #sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
            try:
                sch_day = self.calendar.loc[timestampDate.date()]
            except KeyError:
                sch_day = None
            candles_collected = 0
            timestampAdj = timestampDate    # this timestamp is less than a period prior to the open of candle we need to add
            moveToNextDay = False
            while candles_collected < n_post:
                if sch_day is None or moveToNextDay:   # timestamp falls on weekend/holiday  --> go to next day
                    period_start = period_start + pd.DateOffset(days=1)
                    period_end = period_end + pd.DateOffset(days=1)
                    #sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
                    #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=period_start.date(), end=period_end.date()))
                    #sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                    try:
                        sch_day = self.calendar.loc[period_start.date()]
                    except KeyError:
                        sch_day = None
                    moveToNextDay = False
                else:
                    timestampAdj = max(timestampAdj, sch_day['market_open']-pd.DateOffset(seconds=period_s))   # timestamp before open --> shift to last second before market open 
                    k = int((timestampAdj - sch_day['market_open']).total_seconds()/period_s+1)
                    candle_start = sch_day['market_open'] + pd.DateOffset(seconds=k*period_s)
                    if candle_start >= sch_day['market_close']:
                        moveToNextDay = True
                        continue
                    candle_end = min(sch_day['market_close'], sch_day['market_open'] + pd.DateOffset(seconds=(k+1)*period_s)) #- pd.DateOffset(seconds=1)
                    candleOpenCloseTime['post'].append((candle_start, candle_end))
                    timestampAdj = candle_start
                    candles_collected += 1
            
        elif timeframe_sym=='d':
            try:
                sch_day = self.calendar.loc[timestampDate.date()]
            except KeyError:
                sch_day = None
            offset_pre = 0
            offset_post = 0
            if (not sch_day is None and timestampDate >= sch_day['market_open'] and timestampDate < sch_day['market_close']):   # timestamp falls within the candle - populate current candle
                candleOpenCloseTime['current'] = (sch_day['market_open'], sch_day['market_close']) 
            if not sch_day is None:
                if timestampDate >= sch_day['market_close']:  # timestamp after the candle close, this period should be included into 'pre' list
                    offset_pre = 1
                if timestampDate < sch_day['market_open']:  # timestamp before the candle open, this period should be included into 'post' list
                    offset_post = 1

            # pre candles
            start_pre = self.calendar.index.searchsorted(timestampDate.date(), side='left')-1 + offset_pre
            for ii in range(n_pre):
                if start_pre-ii < 0:
                    break
                sch_day = self.calendar.iloc[start_pre-ii]
                if (not sch_day.empty):
                    candleOpenCloseTime['pre'].append((sch_day['market_open'], sch_day['market_close']))
            # post candles
            start_post = self.calendar.index.searchsorted(timestampDate.date(), side='right') - offset_post
            for ii in range(n_post):
                if start_post+ii >= len(self.calendar.index):
                    break
                sch_day = self.calendar.iloc[start_post+ii]
                if (not sch_day.empty):
                    candleOpenCloseTime['post'].append((sch_day['market_open'], sch_day['market_close']))
            '''
            this_period_start = timestampDate.replace(hour=0, minute=0, second=0)
            this_period_end = timestampDate.replace(hour=23, minute=59, second=59)
            period_offset = pd.DateOffset(days=1)        
            candles_collected = 0
            period_start = this_period_start
            period_end = this_period_end
            while candles_collected < n_pre:
                #sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
                sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=period_start.date(), end=period_end.date()))
                sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                if (not sch_day.empty and timestampDate >= sch_day.iloc[0]['market_close']):
                    #candleOpenCloseTime['pre'].append((sch_day.iloc[0]['market_open'], sch_day.iloc[0]['market_close'] - pd.DateOffset(seconds=1)))
                    candleOpenCloseTime['pre'].append((sch_day.iloc[0]['market_open'], sch_day.iloc[0]['market_close']))
                    candles_collected+=1
                period_start = period_start - period_offset
                period_end = period_end - period_offset
            candles_collected = 0
            period_start = this_period_start
            period_end = this_period_end
            while candles_collected < n_post:
                period_start = period_start + period_offset
                period_end = period_end + period_offset
                #sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
                sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=period_start.date(), end=period_end.date()))
                sch_day = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                if (not sch_day.empty):
                    #candleOpenCloseTime['post'].append((sch_day.iloc[0]['market_open'], sch_day.iloc[0]['market_close'] - pd.DateOffset(seconds=1)))
                    candleOpenCloseTime['post'].append((sch_day.iloc[0]['market_open'], sch_day.iloc[0]['market_close']))
                    candles_collected+=1
            #this_sch = nyse.schedule(start_date=this_period_start, end_date=this_period_end)
            sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=this_period_start.date(), end=this_period_end.date()))
            this_sch = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
            if (not this_sch.empty) and (timestampDate < this_sch.iloc[0]['market_close']) and (timestampDate >= this_sch.iloc[0]['market_open']):   # Timestamp falls within the candle - populate current candle
                #candleOpenCloseTime['current'] = (this_sch.iloc[0]['market_open'], this_sch.iloc[-1]['market_close'] - pd.DateOffset(seconds=1))
                candleOpenCloseTime['current'] = (this_sch.iloc[0]['market_open'], this_sch.iloc[-1]['market_close'])
            '''
        else:
            # Yearly, Quarterly, Monthly, Weekly
            offset_pre = 1  # offset from current date to previous candles (set to 0 if timestamp is after the candle close to include this period to 'pre' list)
            offset_post = 1
            offset_7days = pd.DateOffset(days=7)    # used in all timeframes from Daily and longer
            offset_1sec = pd.DateOffset(seconds=1)  # used to adjust the end of the candle to be 1 sec before the next candle starts
            if timeframe_sym=="y":
                this_period_start = timestampDate.replace(month=1, day=1, hour=0, minute=0, second=0)
                #this_period_end = timestampDate.replace(month=12, day=31, hour=23, minute=59, second=59)
                period_offset = pd.DateOffset(years=1)
            elif timeframe_sym=='q':
                quarterStartMonth = 3*((timestampDate.month-1)//3)+1
                #quarterEndMonth = 3*((timestampDate.month-1)//3+1)
                this_period_start = timestampDate.replace(month=quarterStartMonth, day=1, hour=0, minute=0, second=0) 
                #this_period_end = timestampDate.replace(month=quarterEndMonth, day=1, hour=23, minute=59, second=59) + pd.offsets.MonthEnd(0) 
                period_offset = pd.DateOffset(months=3)
            elif timeframe_sym=='m':
                this_period_start = timestampDate.replace(day=1, hour=0, minute=0, second=0)
                #nextMonth_start = (this_period_start + pd.Timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0)
                #this_period_end = nextMonth_start - pd.Timedelta(seconds=1)
                #this_period_end = timestampDate.replace(day=1, hour=23, minute=59, second=59) + pd.offsets.MonthEnd(0)
                period_offset = pd.DateOffset(months=1)
            elif timeframe_sym=='w':
                this_period_start = timestampDate.replace(hour=0, minute=0, second=0) - pd.Timedelta(days=timestampDate.weekday())
                #this_period_end = timestampDate.replace(hour=23, minute=59, second=59) + pd.Timedelta(days=6-timestampDate.weekday())
                period_offset = pd.DateOffset(days=7)
            else:
                raise ValueError(f"Unsupported timeframe in HTF branch: {timeframe_sym}")

            this_period_end = this_period_start + period_offset - offset_1sec
            #schedule_start = nyse.schedule(start_date=this_period_start, end_date=this_period_start+offset_7days)
            #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=this_period_start.date(), end=(this_period_start+offset_7days).date()))
            #schedule_start = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
            #schedule_end = nyse.schedule(start_date=this_period_end-offset_7days, end_date=this_period_end)
            #sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=(this_period_end-offset_7days).date(), end=this_period_end.date()))
            #schedule_end = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
            schedule_start_id = self.calendar.index.searchsorted(this_period_start.date(), side='left')
            schedule_end_id = self.calendar.index.searchsorted(this_period_end.date(), side='right')-1
            #if schedule_start_id is None or schedule_end_id is None:
            #    print(f"Timestamp {timestampDate} is outside of the calendar range")
            #    return candleOpenCloseTime

            if timestampDate >= self.calendar.iloc[schedule_end_id]['market_close']:  # timestamp after the candle close, this period should be included into 'pre' list
                offset_pre = 0
            if timestampDate < self.calendar.iloc[schedule_start_id]['market_open']:  # timestamp before the candle open, this period should be included into 'post' list
                offset_post = 0
            for ii in range(offset_pre, n_pre+offset_pre):  # Populate previous candles
                candle_start_id = self.calendar.index.searchsorted((this_period_start-ii*period_offset).date(), side='left')
                candle_end_id = self.calendar.index.searchsorted((this_period_start-(ii-1)*period_offset-offset_1sec).date(), side='right')-1
            #TODO - check if candle start is within the calendar range
                candleOpenCloseTime['pre'].append((self.calendar.iloc[candle_start_id]['market_open'], self.calendar.iloc[candle_end_id]['market_close']))
                '''
                #candle_start = nyse.schedule(start_date=this_period_start-ii*period_offset, end_date=this_period_start-ii*period_offset+offset_7days)
                sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=(this_period_start-ii*period_offset).date(), end=(this_period_start-ii*period_offset+offset_7days).date()))
                candle_start =  pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                candle_start = candle_start.iloc[0]['market_open']
                #candle_end = nyse.schedule(start_date=this_period_start-(ii-1)*period_offset-offset_1sec-offset_7days, end_date=this_period_start-(ii-1)*period_offset-offset_1sec)
                sch_day = self.trading_client.get_calendar(GetCalendarRequest(
                    start=(this_period_start-(ii-1)*period_offset-offset_1sec-offset_7days).date(), 
                    end=(this_period_start-(ii-1)*period_offset-offset_1sec).date()))
                candle_end =  pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                candle_end = candle_end.iloc[-1]['market_close'] #- offset_1sec
                candleOpenCloseTime['pre'].append((candle_start, candle_end))
                '''
            for ii in range(offset_post, n_post+offset_post):   # Populate future candles
                candle_start_id = self.calendar.index.searchsorted((this_period_start+ii*period_offset).date(), side='left')
                candle_end_id = self.calendar.index.searchsorted((this_period_start+(ii+1)*period_offset-offset_1sec).date(), side='right')-1
                #TODO - check if candle end is within the calendar range
                candleOpenCloseTime['post'].append((self.calendar.iloc[candle_start_id]['market_open'], self.calendar.iloc[candle_end_id]['market_close']))
                '''
                #candle_start = nyse.schedule(start_date=this_period_start+ii*period_offset, end_date=this_period_start+ii*period_offset+offset_7days)
                sch_day = self.trading_client.get_calendar(GetCalendarRequest(start=(this_period_start+ii*period_offset).date(), end=(this_period_start+ii*period_offset+offset_7days).date()))
                candle_start = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])
                candle_start = candle_start.iloc[0]['market_open']
                #candle_end = nyse.schedule(start_date=this_period_start+(ii+1)*period_offset - offset_7days, end_date=this_period_start+(ii+1)*period_offset - offset_1sec)
                sch_day = self.trading_client.get_calendar(GetCalendarRequest(
                    start=(this_period_start+(ii+1)*period_offset - offset_7days).date(), 
                    end=(this_period_start+(ii+1)*period_offset - offset_1sec).date()))
                candle_end = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in sch_day])

                candle_end = candle_end.iloc[-1]['market_close'] #- offset_1sec
                candleOpenCloseTime['post'].append((candle_start, candle_end))  
                '''      
            if (timestampDate < self.calendar.iloc[schedule_end_id]['market_close'] and timestampDate >= self.calendar.iloc[schedule_start_id]['market_open']):   # Timestamp falls within the candle - populate current candle
                candleOpenCloseTime['current'] = (self.calendar.iloc[schedule_start_id]['market_open'], self.calendar.iloc[schedule_end_id]['market_close']) #- pd.DateOffset(seconds=1))
        
        # convert all timestamps to desired timezone
        for ii in range(len(candleOpenCloseTime['pre'])):
            candleOpenCloseTime['pre'][ii] = tuple(map(lambda x: x.tz_convert(tz), candleOpenCloseTime['pre'][ii]))
        if candleOpenCloseTime['current']:
            candleOpenCloseTime['current'] = tuple(map(lambda x: x.tz_convert(tz), candleOpenCloseTime['current']))
        for ii in range(len(candleOpenCloseTime['post'])):
            candleOpenCloseTime['post'][ii] = tuple(map(lambda x: x.tz_convert(tz), candleOpenCloseTime['post'][ii]))
        return candleOpenCloseTime
    
    def getCandleList(self, timeframe: str, start_time: int, end_time: int) -> Tuple[List[pd.Timestamp], List[pd.Timestamp]]:
        if not timeframe in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {timeframe}. Supported timeframes are: {SUPPORTED_TIMEFRAMES}")
        start_dt = pd.to_datetime(start_time, unit='s', utc=True).tz_convert('America/New_York')
        end_dt = pd.to_datetime(end_time, unit='s', utc=True).tz_convert('America/New_York')
        if start_dt >= end_dt:
            raise ValueError("start_time must be earlier than end_time")
        if start_dt.date() < self.calendar.index[0] or end_dt.date() > self.calendar.index[-1]:  # timestamp is outside of the calendar range
            logger.error(f"Start time {start_dt} or end time {end_dt} is outside of the calendar range")
            return [], []
        if timeframe in ['m60', 'm30', 'm15', 'm5', 'm1']:
            period_s = int(timeframe[1:])*60
            candle_count = (end_dt - start_dt).total_seconds()/period_s + 1
        elif timeframe=='d':
            candle_count = (end_dt - start_dt).days + 1
        elif timeframe=='w':
            candle_count = (end_dt - start_dt).days//7 + 1
        elif timeframe=='m':
            candle_count = (end_dt.year - start_dt.year)*12 + end_dt.month - start_dt.month + 1
        elif timeframe=='q':
            candle_count = (end_dt.year - start_dt.year)*4 + (end_dt.month-1)//3 - (start_dt.month-1)//3 + 1
        elif timeframe=='y':
            candle_count = end_dt.year - start_dt.year + 1
        else:
            raise ValueError(f"Unsupported timeframe: {timeframe}. Supported timeframes are: {SUPPORTED_TIMEFRAMES}")
        candle_count = int(candle_count)
        candle_list = []
        candle_list_candidate = self.getCandleOpenCloseTime(start_dt.timestamp(), timeframe, n_post=candle_count)
        if candle_list_candidate['current']:
            candle_list.extend([candle_list_candidate['current']])
        candle_list.extend(candle_list_candidate['post'])
        candle_list_open  = [c[0] for c in candle_list if (c[0] >= start_dt and c[1] <= end_dt)]
        candle_list_close = [c[1] for c in candle_list if (c[0] >= start_dt and c[1] <= end_dt)]
        return candle_list_open, candle_list_close
    
if __name__ == "__main__":
    #TF = 'm15'
    timestamp_dt = pd.to_datetime("2024-1-2 12:59:00").tz_localize('America/Los_Angeles')
    timestamp_s = timestamp_dt.timestamp()
    TF = 'm15'
    mtm = MarketTimeManager()
    #timestamp_s = 1732026600.0
    candleSet = mtm.getCandleOpenCloseTime(timestamp_s, TF, 3, 4)
    print('Timestamp: ' + str(timestamp_dt) + '\tTimeframe: ' + TF + '\n')
    print('Previous candles:')
    for pre_candle in candleSet['pre']:
        print(pre_candle)
        #print(tuple(map(lambda x: x.tz_convert('America/Los_Angeles'), pre_candle)))
    if candleSet['current']:
        #print('\nCurrent candle: '+ str(tuple(map(lambda x: str(x.tz_convert('America/Los_Angeles')), candleSet['current']))) + '\n')
        print('\nCurrent candle: '+ str(candleSet['current']) + '\n')
    else:
        print('\nCurrent candle: None \n')
    print('Future candles:')
    for post_candle in candleSet['post']:
        print(post_candle)
        #print(tuple(map(lambda x: x.tz_convert('America/Los_Angeles'), post_candle)))
    if mtm.isMarketOpen(timestamp_dt):
        print('Market is open at the timestamp ' + timestamp_dt.strftime('%Y-%m-%d %H:%M:%S %Z'))
    else:
        print('Market is closed at the timestamp ' + timestamp_dt.strftime('%Y-%m-%d %H:%M:%S %Z'))
    
    if mtm.isMarketOpen():
        print('It is ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z') + ' and the market is open.')
    else:
        print('It is ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z') + ' and the market is closed.')
   
