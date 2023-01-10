from datetime import datetime
from dateutil.relativedelta import relativedelta
import candles 
import util
import patterns

class Ticker:
    # Ticker with history at multiple time frames
    # candles is dictionary of 3-candles for each time frame as
    #   {timeframe: [array of Candles]}
    # array of candles is sorted in time, with the first element being most recent (live) candle
    def __init__(self, symbol, TDSession):
        self.symbol = symbol
        self.session = TDSession
        self.candles = {}
        self.__getLast3Candles()
        self.lastUpdated = datetime.now()
        self.thisCandleClose = {}
        self.nextCandleOpen = {}
        for t in self.candles.keys():
            (thisClose, nextOpen) = util.getCandleChange_ms(1000*self.lastUpdated.timestamp(), t)
            self.thisCandleClose[t] = thisClose
            self.nextCandleOpen[t] = nextOpen
        #self.debug_print()

        self.status = util.TickerStatus.OUT
        self.entryPrice = 0.0
        self.stopPrice = 0.0 # Unused for now
        self.targetPrice = 0.0

        self.logger = util.strat_logger("Ticker_"+self.symbol, "strat_"+self.symbol+".log")
        self.logger.logger.debug("Ticker created: " + str(self))

    def __str__(self):
        output_str = "Symbol: " + str(self.symbol) + " Status: " + str(self.status) + " Last updated: " + str(self.lastUpdated) + " Candles: "
        for c in self.candles.keys():
            output_str += "\n\t"
            #print("We're debugging candles for timeframe: " + str(c))
            #print(self.candles)
            #print(self.candles[c])
            output_str += c + ": "
            if self.candles[c] is None:
                output_str += "Candle is empty!!!"
                continue
            for t in self.candles[c]:
                output_str += str(t) + " "
            #output_str += c + ": " + str(self.candles[c]) + " "
        return output_str

    
    def getTFC(self, timeframe=[]):
        tfc = {}
        # If timeframe is not specified - return string representing time frame continuity in order: Y, Q, M, W, D, 60min, 30min, 15min, 5min
        # If timeframe is specified - then only that time frame is reported
        if len(timeframe) == 0:
            #timeframe = DEFAULT_TIMEFRAME_ARR
            timeframe = self.candles.keys()
        for current_timeframe in timeframe:
            if self.candles[current_timeframe] is None:
                tfc[current_timeframe] = 'X'
                continue
            tfc[current_timeframe] = self.candles[current_timeframe][0].get_direction()
        return tfc

    def to_string(self):
        # Return symbol name, TFC
        return self.symbol + ":" + str(self.getTFC())

    def debug_print(self):
        print("Symbol: " + str(self.symbol))
        for t in self.candles.keys():
            print("Timeframe: " + t)
            for c in self.candles[t]:
                print(c)
            print("Current candle closes: " + str(datetime.fromtimestamp(self.thisCandleClose[t]/1000)))
            print("Next candle opens: " + str(datetime.fromtimestamp(self.nextCandleOpen[t]/1000)))


    @staticmethod
    def get_candle_given_data(data):
        # Return array of 3x Candles given data from TD API
        # TODO: check that data is not empty!
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
        # TODO: check that data is not empty!
        lastCandleTimestamp = data[-1]["datetime"]//1000   # convert ms into seconds, timestamp is in epoch format 
        lastCandleMonth = datetime.fromtimestamp(lastCandleTimestamp).month+1   # this is a hack, TD returns previous month 10pm timestamp here 
        numMonthInThisQuarter = lastCandleMonth%3
        if numMonthInThisQuarter == 0:  # if this month is last month of quarter 
            numMonthInThisQuarter = 3
        candle_quarter_1 = Ticker.__mergeCandles(data[-numMonthInThisQuarter:])
        candle_quarter_2 = Ticker.__mergeCandles(data[-numMonthInThisQuarter-3:-numMonthInThisQuarter])
        candle_quarter_3 = Ticker.__mergeCandles(data[-numMonthInThisQuarter-6:-numMonthInThisQuarter-3])
        candle_quarter_4 = Ticker.__mergeCandles(data[-numMonthInThisQuarter-9:-numMonthInThisQuarter-6])
        # Check if any of the quarters are empty
        if (candle_quarter_1 == {}) or (candle_quarter_2 == {}) or (candle_quarter_3 == {}) or (candle_quarter_4 == {}):
            print("We're working on a ticker which doesn't have enough data to create 4 quarters!!")
            return None

        #print("Quarter candles: \n" + str(candle_quarter_1) + " \n" + str(candle_quarter_2) + " \n" + str(candle_quarter_3) + " \n" + str(candle_quarter_4))

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
        # TODO: check that data is not empty!
        lastCandleTimestamp = data[-1]["datetime"]//1000   # convert ms into seconds, timestamp is in epoch format 
        lastCandleMinute = datetime.fromtimestamp(lastCandleTimestamp).minute
        candle_list = []
        if lastCandleMinute >= 30:  # last candle is first half of the hour
            candle_hour_1 = candles.Candle (data[-1]["datetime"], data[-1]["open"], data[-1]["high"], data[-1]["low"], data[-1]["close"], data[-2]["high"], data[-2]["low"])
            merged_candle_two = Ticker.__mergeCandles([data[-2], data[-3]])
            merged_candle_three = Ticker.__mergeCandles([data[-4], data[-5]])
            merged_candle_four = Ticker.__mergeCandles([data[-6], data[-7]])
            if (merged_candle_two is None) or (merged_candle_three is None) or (merged_candle_four is None):
                print("We're working on a ticker which doesn't have enough data to create 4 hours!!")
                return None
            candle_hour_2 = candles.Candle (merged_candle_two["datetime"], merged_candle_two["open"], merged_candle_two["high"], merged_candle_two["low"], merged_candle_two["close"], merged_candle_three["high"], merged_candle_three["low"])
            candle_hour_3 = candles.Candle (merged_candle_three["datetime"], merged_candle_three["open"], merged_candle_three["high"], merged_candle_three["low"], merged_candle_three["close"], merged_candle_four["high"], merged_candle_four["low"])
        else: # last candle is second half of the hour
            merged_candle_one = Ticker.__mergeCandles([data[-1], data[-2]])
            merged_candle_two = Ticker.__mergeCandles([data[-3], data[-4]])
            merged_candle_three = Ticker.__mergeCandles([data[-5], data[-6]])
            merged_candle_four = Ticker.__mergeCandles([data[-7], data[-8]])
            if (merged_candle_one is None) or (merged_candle_two is None) or (merged_candle_three is None) or (merged_candle_four is None):
                print("We're working on a ticker which doesn't have enough data to create 4 hours!!")
                return None
            candle_hour_1 = candles.Candle (merged_candle_one["datetime"], merged_candle_one["open"], merged_candle_one["high"], merged_candle_one["low"], merged_candle_one["close"], merged_candle_two["high"], merged_candle_two["low"])
            candle_hour_2 = candles.Candle (merged_candle_two["datetime"], merged_candle_two["open"], merged_candle_two["high"], merged_candle_two["low"], merged_candle_two["close"], merged_candle_three["high"], merged_candle_three["low"])
            candle_hour_3 = candles.Candle (merged_candle_three["datetime"], merged_candle_three["open"], merged_candle_three["high"], merged_candle_three["low"], merged_candle_three["close"], merged_candle_four["high"], merged_candle_four["low"])
        candle_list = [candle_hour_1, candle_hour_2, candle_hour_3]
        return candle_list

    def __getLast3Candles(self, timeframe=[]):
        # return array of 3x Candles of specified timeframe. 
        # Timeframe options: "y", "q", "m", "w", "d", "m60", "m30", "m15", "m5"
        # If called outside of market hours, we don't need to specify end day since get_price_history returns candles including today
        # If called during market hours, without specifying end date, the output excludes current day. Need to provide valid start and end day 
        # This will populate intraday candles incorrectly for days with short trading hours because TD reports them as regular hours anyway  
        # TODO: unnecessary if fork - market open condition should work either way
        currentDateTime = datetime.now()
        currentTimeStamp_ms = int(1000*currentDateTime.timestamp())
        #previousDayTimeStamp_ms = int(1000*util.getPreviousTradingDay().timestamp())
        #relativedelta(months=n)
        #isMarketOpen = util.isMarketOpen(currentTimeStamp_ms)
        isMarketOpen = True
        if isMarketOpen:
            Period    = None 
            endDate   = currentTimeStamp_ms
            startDate = {}
            for t in util.timeframe_LUT.keys():
                startDate[t] = util.getStartOf3Candles(endDate, t)

        else:
            Period    = 1  
            endDate   = None            
            startDate = {}
            for t in util.timeframe_LUT.keys():
                startDate[t] = None           
                   
        #TODO: Get yearly candle
        #year = [currentDateTime.year - 2, currentDateTime.year - 1, currentDateTime.year]

        # Should be universal for all timeframes:
        #for t in self.candles.keys():
        #    data = self.session.get_price_history(symbol = self.symbol, period_type = util.timeframe_LUT[t][1], period=1, start_date=None, end_date=None, frequency_type = util.timeframe_LUT[t][2], frequency = util.timeframe_LUT[t][3], extended_hours=False)
        #    candle = data["candles"]
        #    if (t == 'q'):
        #        self.candles[t] = Ticker.get_quarter_candle_given_data(candle)
        #    elif (t == 'm60'):
        #        self.candles[t] = Ticker.get_hour_candle_given_data(candle)
        #    else:
        #       self.candles[t] = self.get_candle_given_data(candle)

        # Get quarterly candle
        # Get monthly candles and stitch them together to form quarter
        data = self.session.get_price_history(symbol=self.symbol, period_type="year", period=Period, start_date=startDate["q"], end_date=endDate, frequency_type="monthly", frequency=1, extended_hours=False)
        candle = data["candles"] 
        self.candles["q"] = self.get_quarter_candle_given_data(candle)
        #print("Quarterly candles:")
        #for c in self.candles["q"]:
        #    print(c)
        # Get monthly candles
        # Will use candle data from previous API call
        #data = self.session.get_price_history(symbol=self.symbol, period_type="year", period=1, start_date=None, end_date=None, frequency_type="monthly", frequency=1, extended_hours=False)
        #candle = data["candles"]
        self.candles["m"] = self.get_candle_given_data(candle)
        #print("Monthly candles:")
        #for c in self.candles["m"]:
        #    print(c)
        # Get weekly candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=Period, start_date=startDate["w"], end_date=endDate, frequency_type="weekly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["w"] = self.get_candle_given_data(candle)
        
        # Get daily candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=Period, start_date=startDate["d"], end_date=endDate, frequency_type="daily", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["d"] = self.get_candle_given_data(candle)
         
        # Get hourly candle. Somehow TD API does not support 60min candles natively, so we stitch 2x 30min candles 
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=Period, start_date=startDate["m60"], end_date=endDate, frequency_type="minute", frequency=30, extended_hours=False)
        candle = data["candles"]
        self.candles["m60"] = self.get_hour_candle_given_data(candle)
        #print("Hourly candles:")
        #for c in self.candles["m60"]:
        #    print(c)
            
        # Get 30min candle
        # Will use candle data from previous API call 
        self.candles["m30"] = self.get_candle_given_data(candle)
        
        # Get 15min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=Period, start_date=startDate["m15"], end_date=endDate, frequency_type="minute", frequency=15, extended_hours=False)
        candle = data["candles"]
        self.candles["m15"] = self.get_candle_given_data(candle)
        
        # Get 5min candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="day", period=Period, start_date=startDate["m5"], end_date=endDate, frequency_type="minute", frequency=5, extended_hours=False)
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
        result = {"datetime": candleList[minpos]["datetime"], "open": candleList[minpos]["open"], "high": max(high),
                  "low": min(low), "close": candleList[maxpos]["close"], "volume": sum(volume)}
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

    def update(self, strategy):
        # TODO: description
        self.logger.logger.debug("The beginning of an update call: " + str(self))
        #data = self.session.get_quotes([self.symbol])
        counter = 0
        while counter < util.request_retry_num:
            try:
                data = self.session.get_quotes([self.symbol])
            except:
                self.logger.logger.debug("Exception occurred during request for quotes. Attempt # " + str(counter))
                counter = counter + 1
            else:
                if not data:    # TD API quote sometimes returns no data, retry getting quote up to 10 times before giving up completely
                    self.logger.logger.debug("Quote request returned no data. Attempt # " + str(counter))
                    counter = counter + 1
                else:           # We get here if no exception and valid data got pulled
                    break
        if counter == util.request_retry_num:   # We get here if counter got to max attempts allowed + 1
            self.logger.logger.debug("Quote returned no data too many times")
            exit(-1)
        
        #while not data:   # TD API quote sometimes returns no data, retry getting quote up to 10 times before giving up completely
        #    counter = counter + 1
        #    data = self.session.get_quotes([self.symbol])
        #    self.logger.logger.debug("Quote request returned no data")
        #    if counter >= 10:
        #        self.logger.logger.debug("Quote returned no data too many times")
        #        exit(-1)
        #print("Quote: ", data)

        # update close prices (for live candles from the ticker) using the market price
        self.logger.logger.debug("Updating close prices")
        self.updateClose(data[self.symbol]["regularMarketLastPrice"])

        # update (if necessary) high and low of live candles
        self.logger.logger.debug("Updating high and low prices")
        self.updateHighLow(data[self.symbol]["regularMarketLastPrice"])

        # create new candles (if necessary; based on the current timeframe)
        self.logger.logger.debug("Inserting new candles")
        self.insertCandle(data[self.symbol]["regularMarketLastPrice"], data[self.symbol]["regularMarketTradeTimeInLong"])

        # detect patterns from the strategy
        self.logger.logger.debug("Detecting strategy patterns")
        if self.status == util.TickerStatus.OUT:
            signal = strategy.detect(self.candles, self.logger)
            if signal is None:
                self.logger.logger.info("No ENTRY signal detected")
            else:
                self.status = signal
                self.entryPrice = data[self.symbol]["regularMarketLastPrice"]
                self.logger.logger.info("ENTRY signal detected: " + str(signal) + " at price " + str(self.entryPrice))
        # signal exiting from the position
        elif self.status == util.TickerStatus.LONG or self.status == util.TickerStatus.SHORT:
            signal = strategy.exit_signal(self.candles, self.logger)
            if not signal:
                self.logger.logger.info("No EXIT signal detected")
            else:
                self.logger.logger.info("EXIT signal detected: " + str(signal) + " at price " + str(data[self.symbol]["regularMarketLastPrice"]) + " where entry price was " + str(self.entryPrice))
                self.status = util.TickerStatus.OUT

        self.lastUpdated = datetime.now()
        self.logger.logger.debug("The end of an update call: " + str(self))

    def insertCandle (self, price, timestamp):
        # Insert new candle into the candle list if necessary
        candles_before_insertion = "Candles before insertion: "
        candles_after_insertion = "Candles after insertion: "
        for t in self.candles.keys():
            candles_before_insertion += t + ": "
            candles_after_insertion += t + ": "
            if timestamp >= self.nextCandleOpen[t]:
                for c in self.candles[t]:
                    candles_before_insertion += str(c) + " "
                (thisClose, nextOpen) = util.getCandleChange_ms(timestamp, t)
                #if (timestamp - self.candles[t][-1].timestamp_ms) > util.timeframe_LUT[t][0]:
                prev_high = self.candles[t][0].high
                prev_low = self.candles[t][0].low
                newCandle = candles.Candle(timestamp, price, price, price, price, prev_high, prev_low)
                self.candles[t].insert(0, newCandle)
                self.candles[t].pop()
                self.thisCandleClose[t] = thisClose
                self.nextCandleOpen[t] = nextOpen
                #self.debug_print()
                for c in self.candles[t]:
                    candles_after_insertion += str(c) + " "
            else:
                candles_before_insertion += "No insertion is done "
                candles_after_insertion += "No insertion is done "

        self.logger.logger.debug(candles_before_insertion)
        self.logger.logger.debug(candles_after_insertion)

    def updateClose(self, close_price):
        # Update close prices of live candles
        debug_string = "Close price: " + str(close_price) + " ; Update in candles: "
        for t in self.candles.keys():
            debug_string += t + ": "
            if self.candles[t] is None:
                debug_string += "No candles for this timeframe "
                continue
            debug_string += str(self.candles[t][0].close) + " "
            self.candles[t][0].close = close_price
        self.logger.logger.debug(debug_string)

    def updateHighLow(self, price):
        # Update high and low of live candles if necessary
        debug_string = "Current price: " + str(price) + " ; Update in candles: "
        for t in self.candles.keys():
            if self.candles[t] is None:
                debug_string += t + ": No candles for this timeframe "
                continue
            if price > self.candles[t][0].high:
                debug_string += "High: " + t + ": " + str(self.candles[t][0].high) + " "
                self.candles[t][0].high = price
            if price < self.candles[t][0].low:
                debug_string += "Low: " + t + ": " + str(self.candles[t][0].low) + " "
                self.candles[t][0].low = price
        self.logger.logger.debug(debug_string)
   