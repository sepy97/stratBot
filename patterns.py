import candles

def bearish_reversal_212(data):
    # 2-1-2 bearish reversal pattern
    # TODO: DESCRIPTION @@@
    # data - list of candles
    #    __
    # __|  |__
    #   |2U|  |__
    #   |  | 1|  |
    #   |  |__|2D|
    #   |  |  |__|
    #   |__|
    # __|
    #   
    # return - True if pattern is found, False otherwise
    # 
    if len(data) < 3:
        print("Not enough candles!")
        return (-1,-1,-1)
    if (data[0].get_kind() == "2" and data[0].get_direction() == "U") and (data[1].get_kind() == "1"):
        print("CANDIDATE bearish_reversal_212 ")
        if data[2].open < data[1].high and data[2].get_direction() == "D":
            entry = data[1].high
            target = data[0].high
            stop = data[1].low
            return (entry, target, stop)
    return (-1,-1,-1)

def bullish_reversal_212(data):
    # 2-1-2 bullish reversal pattern
    # TODO: DESCRIPTION @@@
    # data - list of candles
    #    __    __
    # __|  |__|  |
    #   |2D|  |2U|
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
        return (-1,-1,-1)
    if (data[0].get_kind() == "2" and data[0].get_direction() == "D") and (data[1].get_kind() == "1"):
        print("CANDIDATE bullish_reversal_212 ")
        if data[2].open > data[1].low and data[2].get_direction() == "U":
            entry = data[1].high
            target = data[0].high
            stop = data[1].low
            return (entry, target, stop)
    return (-1,-1,-1)