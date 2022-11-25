class Candle:
    # Financial candle
    def __init__(self, date, open, high, low, close, prev_high, prev_low):
        self.date = date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.previous_high = prev_high
        self.previous_low = prev_low
    
    def __str__(self):
        return "Date: " + self.date + " Open: " + self.open + " High: " + self.high + " Low: " + self.low + " Close: " + self.close 
    
    def get_kind(self):
        # Return candle kind, either 1, 2 or 3
        # 1 - inside candle
        # 2 - directional candle
        # 3 - outside candle
        if self.high < self.previous_high and self.low > self.previous_low:
            return "1"
        elif self.high > self.previous_high and self.low < self.previous_low:
            return "3"
        elif (self.high > self.previous_high and self.low > self.previous_low) or (self.high < self.previous_high and self.low < self.previous_low):
            return "2"
    
    def get_direction(self):
        # Return candle direction
        if self.open < self.close:
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
                print ("Error: Candle is 2 but has no direction!")
                return "E"
        else:
            return "X"


    def to_string(self):
        # Return candle as string
        return self.get_kind() + self.get_direction()