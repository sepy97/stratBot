import pandas as pd
import logging
logger = logging.getLogger(__name__)

class Candle:
    # Financial candle
    def __init__(self, timestamp_ms, open, high, low, close, prev_high, prev_low, close_ts=None):
        self.timestamp_ms = timestamp_ms    # timestamp in milliseconds (opening time. Documentation says it should be closing time - got confirmation this is a API doc bug. See https://forum.alpaca.markets/t/alpaca-historical-data-bar-timestamp/15867/2)
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.previous_high = prev_high
        self.previous_low = prev_low
        self.open_ts = self.timestamp_ms/1000
        self.close_ts = close_ts
    
    def __str__(self):
        return "Date: " + str(self.timestamp_ms) + " Open: " + str(self.open) + " High: " + str(self.high) + " Low: " + str(self.low) + " Close: " + str(self.close) + "\n"
    
    def __repr__(self):
        return "Date: " + str(self.timestamp_ms) + " Open: " + str(self.open) + " High: " + str(self.high) + " Low: " + str(self.low) + " Close: " + str(self.close) + "\n"
    
    def get_kind(self):
        # Return candle kind, either 1, 2 or 3
        # 1 - inside candle
        # 2 - directional candle
        # 3 - outside candle
        if self.high <= self.previous_high and self.low >= self.previous_low:
            '''
             _
            | |_
            | |_|
            |_|
             _ _
            | |_|
            |_|
             _ _
            | | |
            |_|_|
            '''
            return "1"
        elif self.high > self.previous_high and self.low < self.previous_low:
            '''
               _
             _| |
            |_| |
              |_|
            '''
            return "3"
        elif (self.high >= self.previous_high and self.low >= self.previous_low) or (self.high <= self.previous_high and self.low <= self.previous_low):
            '''
               _
             _| |
            | |_|
            |_|
             _
            | |_
            |_| |
              |_|
             _
            | |_
            |_|_|
             _ _
            |_| |
              |_|
            '''
            return "2"
        else:
            logger.error(f"Error: Candle doesn't fit any kind! High: {self.high}, Low: {self.low}, Prev High: {self.previous_high}, Prev Low: {self.previous_low}")
            return "X"
    
    def get_direction(self):
        # Return candle direction
        if (self.open is None) or (self.close is None):
            logger.error("Error: Candle has no direction!")
            return "X"
        elif self.open <= self.close:
            return "G"
        else:
            return "R"

    def get_subtype(self):
        # TODO: description
        if self.get_kind() == "2":
            if self.high > self.previous_high:
                return "U"
            elif self.low < self.previous_low:
                return "D"
            else:
                logger.error("Error: Candle is 2 but has no direction!")
                return "E"
        else:
            return ""
        
    def get_pattern(self):
        # Return H for hammer, S for shooter, or X for neither. Hammer and shooter are defined as open and close being below or above 30% of the candle range.
        if self.open > 0.7*self.high + 0.3*self.low and self.close > 0.7*self.high + 0.3*self.low:
            return "H"
        elif self.open < 0.3*self.high + 0.7*self.low and self.close < 0.3*self.high + 0.7*self.low:
            return "S"
        else:
            return "X"

    def to_string(self):
        # Return candle as string
        #if (self.get_subtype()==None):
        #    print ("Error: subtype is None!")
        #    return self.get_kind()
        return self.get_kind() + self.get_subtype() + self.get_direction() + self.get_pattern()
    
    def to_string_full(self):
        dt = pd.to_datetime(round(self.timestamp_ms/1000), unit='s', utc=True).tz_convert('America/New_York').floor('s')
        return "Date: " + str(dt) + " Open: " + str(self.open) + " High: " + str(self.high) + " Low: " + str(self.low) + " Close: " + str(self.close) + " " + self.to_string() 