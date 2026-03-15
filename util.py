#import datetime

#utc_date_str = '2022-05-26 00:00:00'
#dt = datetime.datetime.strptime(utc_date_str, '%Y-%m-%d %H:%M:%S')

#epoch = datetime.datetime.utcfromtimestamp(0)
#print((dt - epoch).total_seconds())

#import pandas as pd
#import pandas_market_calendars as mcal
from datetime import datetime
#from dateutil.relativedelta import relativedelta

import tomlkit
from pathlib import Path

from enum import Enum

import pytz
import os
import secrets

# dictionary where for each timeframe we have a tuple with (timeframe_LUT, period_type, frequency_type, frequency)
# TODO: add yearly back into LUT
#timeframe_LUT = {'y': (365*24*60*60, "year", "yearly", 1), 'q': (91*24*60*60, "year", "monthly", 1), 'm': (30*24*60*60, "year", "monthly", 1), 'w': (7*24*60*60, "month", "weekly", 1), 'd': (24*60*60, "month", "daily", 1), 'm60': (60*60, "day", "minute", 30), 'm30': (30*60, "day", "minute", 30), 'm15': (15*60, "day", "minute", 15), 'm5': (5*60, "day", "minute", 5)}
#timeframe_LUT = {'q': (91*24*60*60, "year", "monthly", 1), 'm': (30*24*60*60, "year", "monthly", 1), 'w': (7*24*60*60, "month", "weekly", 1), 'd': (24*60*60, "month", "daily", 1), 'm60': (60*60, "day", "minute", 30), 'm30': (30*60, "day", "minute", 30), 'm15': (15*60, "day", "minute", 15), 'm5': (5*60, "day", "minute", 5)}

request_retry_num = 10

class TickerStatus(Enum):
    OUT = 1
    LONG = 2
    SHORT = 3

#timestamp = 1545730073 # timestamp in seconds
#dt_obj = datetime.fromtimestamp(timestamp)

def loadSymbols():
    symbols = []

    dic = tomlkit.loads(Path("config.toml").read_text())
    if "watchlist" in dic:
        for element in dic["watchlist"]:  # type: ignore[union-attr]
            symbols.append(element["symbol"])
    else:
        print("No watchlist in config.toml!!!")
    return symbols

def getLogPath():
    dic = tomlkit.loads(Path("config.toml").read_text())
    return str(dic["paths"]["logs"])

def getUsername():
    config_path = Path("config.toml")
    dic = tomlkit.loads(config_path.read_text())
    if "user" in dic and "name" in dic["user"] and dic["user"]["name"]:
        return str(dic["user"]["name"])
    username = "user_" + secrets.token_hex(2)
    if "user" not in dic:
        dic.add("user", tomlkit.table())
    dic["user"]["name"] = username
    config_path.write_text(tomlkit.dumps(dic))
    return username

def moveLogs(destPath=None, tzone="America/Los_Angeles"):
    if destPath is None:
        dic = tomlkit.loads(Path("config.toml").read_text())
        destPath = str(dic["paths"]["logs"])  # type: ignore[index]
    dt = datetime.now(tz=pytz.timezone(tzone))
    cloudDir = str(destPath+dt.strftime("%Y-%m-%d")+"/"+dt.strftime("%H.%M.%S"))
    os.system("mkdir -p "+cloudDir)
    os.system(str("mv *.log "+cloudDir))


def loadStrategies():
    dic = tomlkit.loads(Path("config.toml").read_text())
    strategies = dic.get("strategies", [])
    return strategies