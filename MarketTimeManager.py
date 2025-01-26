import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime, timedelta

# dictionary where for each timeframe we have a tuple with (timeframe_LUT, period_type, frequency_type, frequency)
# TODO: add yearly back into LUT

timeframe_LUT = {'q': (91*24*60*60*1000, "year", "monthly", 1), 'm': (30*24*60*60*1000, "year", "monthly", 1), 'w': (7*24*60*60*1000, "month", "weekly", 1), 'd': (24*60*60*1000, "month", "daily", 1), 'm60': (60*60*1000, "day", "minute", 30), 'm30': (30*60*1000, "day", "minute", 30), 'm15': (15*60*1000, "day", "minute", 15), 'm5': (5*60*1000, "day", "minute", 5)}

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
def getTodayOpenTime_ms():
    # TODO: check if it is not a trading day
    nyse = mcal.get_calendar('NYSE')
    todayDataFrame = nyse.schedule(str(datetime.now().date()), str(datetime.now().date()))
    openTime = todayDataFrame.iloc[-1]['market_open']
    return int(openTime.timestamp()*1000)

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

def detectTFFlip(current_time, TFperiod, time_quant):
    #opening_time = getOpenCloseAtDay(int(1000*current_time.timestamp()))["open"]
    opening_timestamp = getTodayOpenTime_ms()
    current_timestamp = int(1000*current_time.timestamp())
    delta = current_timestamp - opening_timestamp
    modulo = delta % TFperiod
    if modulo < time_quant*1000:
        return True
    return False

def getProperStartTime(current_time, time_quant):
    # TODO: check for the day to be a trading day
    opening_time = getTodayOpenTime_ms()
    time_quant_ms = time_quant*1000
    delta = int (1000*current_time.timestamp()) - opening_time
    proper_start_time = datetime.fromtimestamp((opening_time + (delta//time_quant_ms + 1)*time_quant_ms)/1000)
    return proper_start_time

# Implementation details:
#     Assume that there is at least one trading day over 7 day period (assumption used in large timeframes)
#     For large time frames (W and larger): detect start and end of calendar period (year, quarter, month, week) containing timestamp, then get daily schedule for the 7 days after start and 7 days prior to end
#     For daily and instraday same approach does not work because holidays can be larger than the entire calendar period of corresponding timeframe
#     

def getCandleOpenCloseTime(timestamp_s, timeframe_sym, n_pre=1, n_post=1, tz='America/New_York'):
    candleOpenCloseTime = {'pre': [], 'current': None, 'post': []}
    nyse = mcal.get_calendar('NYSE')
    timestampDate = pd.to_datetime(timestamp_s, unit='s', utc=True).tz_convert('America/New_York')     # convert to Panda Datetime and ensure it is timezone-aware and in NY timezone

    if timeframe_sym in ['m60', 'm30', 'm15', 'm5', 'm1']:
        period_s = int(timeframe_sym[1:])*60
        this_period_start = timestampDate.replace(hour=0, minute=0, second=0)
        this_period_end = timestampDate.replace(hour=23, minute=59, second=59)
        # populate current candle
        sch_day = nyse.schedule(start_date=this_period_start, end_date=this_period_end)
        if (not sch_day.empty) and (timestampDate >= sch_day.iloc[0]['market_open']) and (timestampDate < sch_day.iloc[0]['market_close']):
            k = int((timestampDate - sch_day.iloc[0]['market_open']).total_seconds()/period_s)  # number of candles prior to timestamp 
            candle_start = sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=k*period_s)
            candle_end = min(sch_day.iloc[0]['market_close'], sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=(k+1)*period_s)) - pd.DateOffset(seconds=1)
            candleOpenCloseTime['current'] = (candle_start, candle_end)
        # populate pre candles
        period_start = this_period_start
        period_end = this_period_end
        sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
        candles_collected = 0
        timestampAdj = timestampDate    # this timestamp is less than a period past the close of candle we need to add
        while candles_collected < n_pre:
            if sch_day.empty or timestampAdj < sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=period_s):   # timestamp falls on weekend/holiday or before open of the second candle of the day --> go to previous day
                period_start = period_start - pd.DateOffset(days=1)
                period_end = period_end - pd.DateOffset(days=1)
                sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
            else:
                timestampAdj = min(timestampAdj, sch_day.iloc[0]['market_close'])   #timestamp after close --> shift to market close
                k = int((timestampAdj - sch_day.iloc[0]['market_open']).total_seconds()/period_s)
                if (timestampAdj >= sch_day.iloc[0]['market_close']) and (sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=k*period_s) < sch_day.iloc[0]['market_close']):    # account for situation when last candle of the day is partial (e.g. last 60min candle is only 30min long)
                    k = k + 1
                candle_start = sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=(k-1)*period_s)
                candle_end = min(sch_day.iloc[0]['market_close'], sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=k*period_s)) - pd.DateOffset(seconds=1)
                candleOpenCloseTime['pre'].append((candle_start, candle_end))
                timestampAdj = candle_start
                candles_collected += 1
        # populate post candles
        period_start = this_period_start
        period_end = this_period_end
        sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
        candles_collected = 0
        timestampAdj = timestampDate    # this timestamp is less than a period prior to the open of candle we need to add
        moveToNextDay = False
        while candles_collected < n_post:
            if sch_day.empty or moveToNextDay:   # timestamp falls on weekend/holiday  --> go to next day
                period_start = period_start + pd.DateOffset(days=1)
                period_end = period_end + pd.DateOffset(days=1)
                sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
                moveToNextDay = False
            else:
                timestampAdj = max(timestampAdj, sch_day.iloc[0]['market_open']-pd.DateOffset(seconds=1))   # timestamp before open --> shift to last second before market open 
                k = int((timestampAdj - sch_day.iloc[0]['market_open']).total_seconds()/period_s + 1)
                candle_start = sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=k*period_s)
                if candle_start >= sch_day.iloc[0]['market_close']:
                    moveToNextDay = True
                    continue
                candle_end = min(sch_day.iloc[0]['market_close'], sch_day.iloc[0]['market_open'] + pd.DateOffset(seconds=(k+1)*period_s)) - pd.DateOffset(seconds=1)
                candleOpenCloseTime['post'].append((candle_start, candle_end))
                timestampAdj = candle_end
                candles_collected += 1

    elif timeframe_sym=='d':
        this_period_start = timestampDate.replace(hour=0, minute=0, second=0)
        this_period_end = timestampDate.replace(hour=23, minute=59, second=59)
        period_offset = pd.DateOffset(days=1)        
        candles_collected = 0
        period_start = this_period_start
        period_end = this_period_end
        while candles_collected < n_pre:
            sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
            if (not sch_day.empty and timestampDate >= sch_day.iloc[0]['market_close']):
                candleOpenCloseTime['pre'].append((sch_day.iloc[0]['market_open'], sch_day.iloc[0]['market_close'] - pd.DateOffset(seconds=1)))
                candles_collected+=1
            period_start = period_start - period_offset
            period_end = period_end - period_offset
        candles_collected = 0
        period_start = this_period_start
        period_end = this_period_end
        while candles_collected < n_post:
            period_start = period_start + period_offset
            period_end = period_end + period_offset
            sch_day = nyse.schedule(start_date=period_start, end_date=period_end)
            if (not sch_day.empty):
                candleOpenCloseTime['post'].append((sch_day.iloc[0]['market_open'], sch_day.iloc[0]['market_close'] - pd.DateOffset(seconds=1)))
                candles_collected+=1
        this_sch = nyse.schedule(start_date=this_period_start, end_date=this_period_end)
        if (not this_sch.empty) and (timestampDate < this_sch.iloc[0]['market_close']) and (timestampDate >= this_sch.iloc[0]['market_open']):   # Timestamp falls within the candle - populate current candle
            candleOpenCloseTime['current'] = (this_sch.iloc[0]['market_open'], this_sch.iloc[-1]['market_close'] - pd.DateOffset(seconds=1))

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
        this_period_end = this_period_start + period_offset - offset_1sec
        schedule_start = nyse.schedule(start_date=this_period_start, end_date=this_period_start+offset_7days)
        schedule_end = nyse.schedule(start_date=this_period_end-offset_7days, end_date=this_period_end)

        if timestampDate >= schedule_end.iloc[-1]['market_close']:  # timestamp after the candle close, this period should be included into 'pre' list
            offset_pre = 0
        if timestampDate < schedule_start.iloc[0]['market_open']:  # timestamp before the candle open, this period should be included into 'post' list
            offset_post = 0
        for ii in range(offset_pre, n_pre+offset_pre):  # Populate previous candles
            candle_start = nyse.schedule(start_date=this_period_start-ii*period_offset, end_date=this_period_start-ii*period_offset+offset_7days)
            candle_start = candle_start.iloc[0]['market_open']
            candle_end = nyse.schedule(start_date=this_period_start-(ii-1)*period_offset-offset_1sec-offset_7days, end_date=this_period_start-(ii-1)*period_offset-offset_1sec)
            candle_end = candle_end.iloc[-1]['market_close'] - offset_1sec
            candleOpenCloseTime['pre'].append((candle_start, candle_end))
        for ii in range(offset_post, n_post+offset_post):   # Populate future candles
            candle_start = nyse.schedule(start_date=this_period_start+ii*period_offset, end_date=this_period_start+ii*period_offset+offset_7days)
            candle_start = candle_start.iloc[0]['market_open']
            candle_end = nyse.schedule(start_date=this_period_start+(ii+1)*period_offset - offset_7days, end_date=this_period_start+(ii+1)*period_offset - offset_1sec)
            candle_end = candle_end.iloc[-1]['market_close'] - offset_1sec
            candleOpenCloseTime['post'].append((candle_start, candle_end))        
        if (timestampDate < schedule_end.iloc[-1]['market_close'] and timestampDate >= schedule_start.iloc[0]['market_open']):   # Timestamp falls within the candle - populate current candle
            candleOpenCloseTime['current'] = (schedule_start.iloc[0]['market_open'], schedule_end.iloc[-1]['market_close'] - pd.DateOffset(seconds=1))
    
    # convert all timestamps to desired timezone
    for ii in range(len(candleOpenCloseTime['pre'])):
        candleOpenCloseTime['pre'][ii] = tuple(map(lambda x: x.tz_convert(tz), candleOpenCloseTime['pre'][ii]))
    if candleOpenCloseTime['current']:
        candleOpenCloseTime['current'] = tuple(map(lambda x: x.tz_convert(tz), candleOpenCloseTime['current']))
    for ii in range(len(candleOpenCloseTime['post'])):
        candleOpenCloseTime['post'][ii] = tuple(map(lambda x: x.tz_convert(tz), candleOpenCloseTime['post'][ii]))
    return candleOpenCloseTime

if __name__ == "__main__":
    #TF = 'm15'
    timestamp_dt = pd.to_datetime("2024-12-30 6:00:00").tz_localize('America/Los_Angeles')
    timestamp_s = timestamp_dt.timestamp()
    TF = 'w'
    #timestamp_s = 1732026600.0
    candleSet = getCandleOpenCloseTime(timestamp_s, TF, 3, 4)
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
   
