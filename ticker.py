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
            timeframe = DEFAULT_TIMEFRAME_ARR
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
        # Timeframe options: "y", "q", "m", "w", "d", "m60", "m15", "m5"
        currentDateTime = datetime.now()
        #relativedelta(months=n)
        
        #TODO: Get yearly candle
        year = [currentDateTime.year - 2, currentDateTime.year - 1, currentDateTime.year]

        #TODO: Get quarterly candle
        
        # Get monthly candles
        data = self.session.get_price_history(symbol=self.symbol, period_type="year", period=1, start_date=None, end_date=None, frequency_type="monthly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["m"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get weekly candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=2, start_date=None, end_date=None, frequency_type="weekly", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["w"] = [candle[-1], candle[-2], candle[-3]]
        
        # Get daily candle
        data = self.session.get_price_history(symbol=self.symbol, period_type="month", period=2, start_date=None, end_date=None, frequency_type="daily", frequency=1, extended_hours=False)
        candle = data["candles"]
        self.candles["d"] = [candle[-1], candle[-2], candle[-3]]
        
        