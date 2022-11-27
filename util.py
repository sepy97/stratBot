#import datetime

#utc_date_str = '2022-05-26 00:00:00'
#dt = datetime.datetime.strptime(utc_date_str, '%Y-%m-%d %H:%M:%S')

#epoch = datetime.datetime.utcfromtimestamp(0)
#print((dt - epoch).total_seconds())

import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime

# dictionary where for each timeframe we have a tuple with (timeframe_LUT, period_type, frequency_type, frequency)
timeframe_LUT = {'y': (365*24*60*60*1000, "year", "yearly", 1), 'q': (91*24*60*60*1000, "year", "monthly", 1), 'm': (30*24*60*60*1000, "year", "monthly", 1), 'w': (7*24*60*60*1000, "month", "weekly", 1), 'd': (24*60*60*1000, "month", "daily", 1), 'm60': (60*60*1000, "day", "minute", 30), 'm30': (30*60*1000, "day", "minute", 30), 'm15': (15*60*1000, "day", "minute", 15), 'm5': (5*60*1000, "day", "minute", 5)}

#timestamp = 1545730073 # timestamp in seconds
#dt_obj = datetime.fromtimestamp(timestamp)
def getPreviousTradingDay():
    nyse = mcal.get_calendar('NYSE')
    date = datetime.now() - pd.tseries.offsets.CustomBusinessDay(1, holidays = nyse.holidays().holidays)
    return date
def getTodayCloseTime_ms():
    nyse = mcal.get_calendar('NYSE')
    todayDataFrame = nyse.schedule(str(datetime.now().date()), str(datetime.now().date()))
    closeTime = todayDataFrame.iloc[-1]['market_close']
    return int(closeTime*1000)
