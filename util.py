#import datetime

#utc_date_str = '2022-05-26 00:00:00'
#dt = datetime.datetime.strptime(utc_date_str, '%Y-%m-%d %H:%M:%S')

#epoch = datetime.datetime.utcfromtimestamp(0)
#print((dt - epoch).total_seconds())

import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime

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
