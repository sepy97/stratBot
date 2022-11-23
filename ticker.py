from datetime import datetime
from dateutil.relativedelta import relativedelta

class Ticker:
    # Ticker with history at multiple time frames
    def __init__(self, symbol, TDSession):
        self.symbol = symbol
        self.session = TDSession        
        self.candles = {}
        self.__getLast3Candles()
        self.lastUpdated = datetime.now()
    
    def __str__(self):
        return self.symbol + ":"
    
    def getTFC(self, timeframe=[]):
        tfc = {}
        # If timeframe is not specified - return string representing time frame continuity in order: Y, Q, M, W, D, 60min, 30min, 15min, 5min
        #DEFAULT_TIMEFRAME_ARR = ["m5", "m15", "m30", "m60", "d", "w", "m", "q", "y"]
        DEFAULT_TIMEFRAME_ARR = ["d", "w", "m"]
        # If timeframe is specified - then only that time frame is reported
        if len(timeframe) == 0:
            #timeframe = DEFAULT_TIMEFRAME_ARR
            timeframe = self.candles.keys()
        for current_timeframe in timeframe:
            if self.candles[current_timeframe][0]["close"] >= self.candles[current_timeframe][0]["open"]:
                tfc[current_timeframe] = "g"
            else:
                tfc[current_timeframe] = "r"
        return tfc

    def to_string(self):
        # Return symbol name, TFC
        return self.symbol + ":" + str(self.getTFC())
    
    def __getLast3Candles(self, timeframe=[]):
        # return array of 3x Candles of specified timeframe. 
        # Timeframe options: "y", "q", "m", "w", "d", "m60", "m30", "m15", "m5"
        currentDateTime = datetime.now()
        #relativedelta(months=n)
        
        #TODO: Get yearly candle
        year = [currentDateTime.year - 2, currentDateTime.year - 1, currentDateTime.year]

        #Get quarterly candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="year", period=1, start_date=None, end_date=None, frequency_type="monthly", frequency=1, extended_hours=False)
        candle = data["candles"]        
        # Find which months fall within this current quarter
        lastCandleTimestamp = candle[-1]["datetime"]//1000   # convert ms into seconds, timestamp is in epoch format 
        lastCandleMonth = datetime.fromtimestamp(lastCandleTimestamp).month+1   # this is a hack, TD returns previous month 10pm timestamp here 
        numMonthInThisQuarter = lastCandleMonth%3
        if numMonthInThisQuarter == 0:  # if this month is last month of quarter 
            numMonthInThisQuarter = 3
        self.candles["q"] = [self.__mergeCandles(candle[-numMonthInThisQuarter:]), self.__mergeCandles(candle[-numMonthInThisQuarter-3:-numMonthInThisQuarter]), self.__mergeCandles(candle[-numMonthInThisQuarter-6:-numMonthInThisQuarter-3])]
        
        # Get monthly candles
        data = self.session.get_price_history(symbol=self.symbol, period_type="year", period=1, start_date=None, end_date=None, frequency_type="monthly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["m"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get weekly candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=1, start_date=None, end_date=None, frequency_type="weekly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["w"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get daily candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=1, start_date=None, end_date=None, frequency_type="daily", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["d"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get hourly candle. Somehow TD API does not support 60min candles natively, so we stitch 2x 30min candles 
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=30, extended_hours=False)
        candle = data["candles"]
        # We need to find if the last 30min candle falls in the beginning or in the end of the hour
        lastCandleTimestamp = candle[-1]["datetime"]//1000   # convert ms into seconds, timestamp is in epoch format 
        lastCandleMinute = datetime.fromtimestamp(lastCandleTimestamp).minute
        if lastCandleMinute >= 30:  # last candle is first half of the hour
            self.candles["m60"] = [candle[-1], self.__mergeCandles([candle[-2], candle[-3]]), self.__mergeCandles([candle[-4], candle[-5]])]    
        else: # last candle is second half of the hour
            self.candles["m60"] = [self.__mergeCandles([candle[-1], candle[-2]]), self.__mergeCandles([candle[-3],candle[-4]]), self.__mergeCandles([candle[-5], candle[-6]])]
                    
        # Get 30min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=30, extended_hours=False)
        candle = data["candles"]
        self.candles["m30"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get 15min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=15, extended_hours=False)
        candle = data["candles"]
        self.candles["m15"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get 5min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=5, extended_hours=False)
        candle = data["candles"]
        self.candles["m5"] = [candle[-1], candle[-2], candle[-3]]
        
           
    @staticmethod    
    def __mergeCandles(candleList):
        # Merge a list of candles into single candle. Assumes subsequent candles 
        if len(candleList) == 1:
            return candleList[0]
        elif len(candleList) == 0:
            return {}
        high = [x["high"] for x in candleList]
        low  = [x["low"] for x in candleList]
        timestamp = [x["datetime"] for x in candleList]
        volume = [x["volume"] for x in candleList]
        minpos = timestamp.index(min(timestamp))
        maxpos = timestamp.index(max(timestamp))
        result = candleList[minpos]
        result["high"] = max(high)
        result["low"] = min(low)
        result["close"] = candleList[maxpos]["close"]
        result["volume"] = sum(volume)
        return result
    
    #@staticmethod    
    #def __mergeTwoCandles(candle1, candle2):
        ## Merge two subsequent candles into single one
        #result = candle1
        #result["high"] = max(candle1["high"], candle2["high"])
        #result["low"]  = min(candle1["low"], candle2["low"])
        #result["volume"] = candle1["volume"] + candles2["volume"]
        ## Determine which candle is first in sequence
        #if candle1["datetime"] < candles2["datetime"]:
            #result["datetime"] = candle1["datetime"]
            #result["open"] = candle1["open"]
            #result["close"] = candle2["close"]
        #else:
            #result["datetime"] = candle2["datetime"]
            #result["open"] = candle2["open"]
            #result["close"] = candle1["close"]
        #return result    