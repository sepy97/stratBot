from datetime import datetime
from dateutil.relativedelta import relativedelta
import candles 

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
        # If timeframe is specified - then only that time frame is reported
        if len(timeframe) == 0:
            #timeframe = DEFAULT_TIMEFRAME_ARR
            timeframe = self.candles.keys()
        for current_timeframe in timeframe:
            tfc[current_timeframe] = self.candles[current_timeframe][0].get_direction()
        return tfc

    def to_string(self):
        # Return symbol name, TFC
        return self.symbol + ":" + str(self.getTFC())
    
    @staticmethod
    def get_candle_given_data(data):
        # Return array of 3x Candles given data from TD API
        candle_list = [candles.Candle(data[-1]["datetime"], data[-1]["open"], data[-1]["high"], data[-1]["low"], data[-1]["close"], data[-2]["high"], data[-2]["low"]),
                       candles.Candle(data[-2]["datetime"], data[-2]["open"], data[-2]["high"], data[-2]["low"], data[-2]["close"], data[-3]["high"], data[-3]["low"]),
                       candles.Candle(data[-3]["datetime"], data[-3]["open"], data[-3]["high"], data[-3]["low"], data[-3]["close"], data[-4]["high"], data[-4]["low"])
                      ]
        return candle_list

    @staticmethod
    def get_quarter_candle_given_data(data):
        # Return array of 3x Candles given data from TD API
        # Specifically for quarter data
        # Receive monthly data and convert to quarterly data by merging 3 months into 1 quarter
        # Find which months fall within this current quarter
        lastCandleTimestamp = data[-1]["datetime"]//1000   # convert ms into seconds, timestamp is in epoch format 
        lastCandleMonth = datetime.fromtimestamp(lastCandleTimestamp).month+1   # this is a hack, TD returns previous month 10pm timestamp here 
        numMonthInThisQuarter = lastCandleMonth%3
        if numMonthInThisQuarter == 0:  # if this month is last month of quarter 
            numMonthInThisQuarter = 3
        candle_quarter_1 = Ticker.__mergeCandles(data[-numMonthInThisQuarter:])
        candle_quarter_2 = Ticker.__mergeCandles(data[-numMonthInThisQuarter-3:-numMonthInThisQuarter])
        candle_quarter_3 = Ticker.__mergeCandles(data[-numMonthInThisQuarter-6:-numMonthInThisQuarter-3])
        candle_quarter_4 = Ticker.__mergeCandles(data[-numMonthInThisQuarter-9:-numMonthInThisQuarter-6])
        candle_list = [candles.Candle(candle_quarter_1["datetime"], candle_quarter_1["open"], candle_quarter_1["high"], candle_quarter_1["low"], candle_quarter_1["close"], candle_quarter_2["high"], candle_quarter_2["low"]),
                       candles.Candle(candle_quarter_2["datetime"], candle_quarter_2["open"], candle_quarter_2["high"], candle_quarter_2["low"], candle_quarter_2["close"], candle_quarter_3["high"], candle_quarter_3["low"]),
                       candles.Candle(candle_quarter_3["datetime"], candle_quarter_3["open"], candle_quarter_3["high"], candle_quarter_3["low"], candle_quarter_3["close"], candle_quarter_4["high"], candle_quarter_4["low"])
                      ]
        return candle_list
    
    @staticmethod
    def get_hour_candle_given_data(data):
        # Return array of 3x Candles given data from TD API
        # Specifically for hour data
        # Receive 30min data and convert to hourly data by merging 2 30min into 1 hour
        # We need to find if the last 30min candle falls in the beginning or in the end of the hour
        lastCandleTimestamp = data[-1]["datetime"]//1000   # convert ms into seconds, timestamp is in epoch format 
        lastCandleMinute = datetime.fromtimestamp(lastCandleTimestamp).minute
        candle_list = []
        if lastCandleMinute >= 30:  # last candle is first half of the hour
            candle_hour_1 = candles.Candle (data[-1]["datetime"], data[-1]["open"], data[-1]["high"], data[-1]["low"], data[-1]["close"], data[-2]["high"], data[-2]["low"])
            merged_candle_two = Ticker.__mergeCandles([data[-2], data[-3]])
            merged_candle_three = Ticker.__mergeCandles([data[-4], data[-5]])
            merged_candle_four = Ticker.__mergeCandles([data[-6], data[-7]])
            candle_hour_2 = candles.Candle (merged_candle_two["datetime"], merged_candle_two["open"], merged_candle_two["high"], merged_candle_two["low"], merged_candle_two["close"], merged_candle_three["high"], merged_candle_three["low"])
            candle_hour_3 = candles.Candle (merged_candle_three["datetime"], merged_candle_three["open"], merged_candle_three["high"], merged_candle_three["low"], merged_candle_three["close"], merged_candle_four["high"], merged_candle_four["low"])
        else: # last candle is second half of the hour
            merged_candle_one = Ticker.__mergeCandles([data[-1], data[-2]])
            merged_candle_two = Ticker.__mergeCandles([data[-3], data[-4]])
            merged_candle_three = Ticker.__mergeCandles([data[-5], data[-6]])
            merged_candle_four = Ticker.__mergeCandles([data[-7], data[-8]])
            candle_hour_1 = candles.Candle (merged_candle_one["datetime"], merged_candle_one["open"], merged_candle_one["high"], merged_candle_one["low"], merged_candle_one["close"], merged_candle_two["high"], merged_candle_two["low"])
            candle_hour_2 = candles.Candle (merged_candle_two["datetime"], merged_candle_two["open"], merged_candle_two["high"], merged_candle_two["low"], merged_candle_two["close"], merged_candle_three["high"], merged_candle_three["low"])
            candle_hour_3 = candles.Candle (merged_candle_three["datetime"], merged_candle_three["open"], merged_candle_three["high"], merged_candle_three["low"], merged_candle_three["close"], merged_candle_four["high"], merged_candle_four["low"])
        candle_list = [candle_hour_1, candle_hour_2, candle_hour_3]
        return candle_list

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
        self.candles["q"] = self.get_quarter_candle_given_data(candle)
        
        # Get monthly candles
        data = self.session.get_price_history(symbol=self.symbol, period_type="year", period=1, start_date=None, end_date=None, frequency_type="monthly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["m"] = self.get_candle_given_data(candle)
        
        # Get weekly candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=1, start_date=None, end_date=None, frequency_type="weekly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["w"] = self.get_candle_given_data(candle)
        
        # Get daily candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=1, start_date=None, end_date=None, frequency_type="daily", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["d"] = self.get_candle_given_data(candle)
        
        # Get hourly candle. Somehow TD API does not support 60min candles natively, so we stitch 2x 30min candles 
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=30, extended_hours=False)
        candle = data["candles"]
        self.candles["m60"] = self.get_hour_candle_given_data(candle)
                    
        # Get 30min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=30, extended_hours=False)
        candle = data["candles"]
        self.candles["m30"] = self.get_candle_given_data(candle)
        
        # Get 15min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=15, extended_hours=False)
        candle = data["candles"]
        self.candles["m15"] = self.get_candle_given_data(candle)
        
        # Get 5min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=1, start_date=None, end_date=None, frequency_type="minute", frequency=5, extended_hours=False)
        candle = data["candles"]
        self.candles["m5"] = self.get_candle_given_data(candle)
           
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