import config as cfg
import candles
import patterns

def receive_candles(ticker):
    cdls = []
    with open(ticker+".csv", "r") as f:
        lines = f.readlines()
        for i in range(1, len(lines)):
            inp_candle = lines[i].split(",")
            prev_candle = lines[i-1].split(",")
            candle = candles.Candle(inp_candle[0], inp_candle[1], inp_candle[2], inp_candle[3], inp_candle[4], prev_candle[2], prev_candle[3])
            cdls.append(candle)
    return cdls

def receive_kinds_of_candles(ticker):
    kinds = []
    with open(ticker+".csv", "r") as f:
        lines = f.readlines()
        for i in range(1, len(lines)):
            inp_candle = lines[i].split(",")
            prev_candle = lines[i-1].split(",")
            candle = candles.Candle(inp_candle[0], inp_candle[1], inp_candle[2], inp_candle[3], inp_candle[4], prev_candle[2], prev_candle[3])
            kinds.append(candle.to_string())
    return kinds

def main():
    #cfg.export_daily_candles("AAPL")
    data = receive_candles("AAPL")
    kinds = receive_kinds_of_candles("AAPL")
    print(kinds)
### For live data we just wait until new candle appears and then we check if there is a pattern
    for i in range(0, len(data)-3):
        data_window = [data[i], data[i+1], data[i+2]]
        (entry, target, stop) = patterns.bullish_reversal_212(data_window)
        if entry != -1:
            print("FOUND BULLISH 2-1-2 pattern")
            print("ENTRY: ", entry)
            print("TARGET: ", target)
            print("STOP: ", stop)
            print(data_window[0].to_string())
            print(data_window[1].to_string())
            print(data_window[2].to_string())
            
        (entry, target, stop) = patterns.bearish_reversal_212(data_window)
        if entry != -1:
            print("FOUND BEARISH 2-1-2 pattern")
            print("ENTRY: ", entry)
            print("TARGET: ", target)
            print("STOP: ", stop)
            print(data_window[0].to_string())
            print(data_window[1].to_string())
            print(data_window[2].to_string())

if __name__ == '__main__':
    main()