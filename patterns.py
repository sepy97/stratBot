import candles

def bearish_reversal_212(data):
    # 2-1-2 bearish reversal pattern
    # TODO: DESCRIPTION @@@
    # data - list of candles
    #    __
    # __|  |__
    #   | 2|  |__
    #   |  | 1|  |
    #   |  |__| 2|
    #   |  |  |__|
    #   |__|
    # __|
    #   
    # return - True if pattern is found, False otherwise
    # 
    if len(data) < 3:
        print("Not enough candles!")
        return False
    if data[0].get_kind() == "2" and data[1].get_kind() == "1":
        print("CANDIDATE bearish_reversal_212 ")
        if data[2].low < data[1].low:
            return True
            # Should compute target and stop-loss here

    return False

def bullish_reversal_212(data):
    # 2-1-2 bullish reversal pattern
    # TODO: DESCRIPTION @@@
    # data - list of candles
    #    __    __
    # __|  |__|  |
    #   | 2|  | 2|
    #   |  | 1|__|
    #   |  |__| 
    #   |  |  
    #   |__|
    # __|
    #   
    # return - True if pattern is found, False otherwise
    # 
    if len(data) < 3:
        print("Not enough candles!")
        return False
    if data[0].get_kind() == "2" and data[1].get_kind() == "1":
        print("CANDIDATE bullish_reversal_212 ")
        if data[2].low > data[1].low:
            return True
            # Should compute target and stop-loss here

    return False