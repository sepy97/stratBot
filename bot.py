import config as cfg
import candles

def print_kinds_of_candles(ticker):
    kinds = []
    with open(ticker+".csv", "r") as f:
        lines = f.readlines()
        for i in range(1, len(lines)):
            inp_candle = lines[i].split(",")
            prev_candle = lines[i-1].split(",")
            candle = candles.Candle(inp_candle[0], inp_candle[1], inp_candle[2], inp_candle[3], inp_candle[4], prev_candle[2], prev_candle[3])
            kinds.append(candle.to_string())
    print(kinds)

def main():
    #cfg.export_daily_candles("AAPL")
    print_kinds_of_candles("AAPL")

if __name__ == '__main__':
    main()