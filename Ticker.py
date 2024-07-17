import threading
from datetime import datetime
import util
from candles import Candle
import strategy

class Ticker(threading.Thread):
    # Ticker with history at multiple time frames
    # candles is dictionary of 3-candles for each time frame as
    #   {timeframe: [array of Candles]}
    # array of candles is sorted in time, with the first element being most recent (live) candle
    def __init__(self, symbol, input_queue, TF, output_queue, ticker_condition, TF_condition, broker_condition, *args, **kwargs):
        super(Ticker, self).__init__(*args, **kwargs)
        self.symbol = symbol
        self.candles = {}
        self.lastUpdated = datetime.now()
        self._stopper = threading.Event()
        self.input_queue = input_queue
        self.TF = TF
        self.output_queue = output_queue
        self.ticker_condition = ticker_condition
        self.TF_condition = TF_condition
        self.broker_condition = broker_condition
        self.status = util.TickerStatus.OUT
        self.entryPrice = 0.0
        self.stopPrice = 0.0
        self.targetPrice = 0.0
        self.strategies = []

    def stopThr(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.is_set()

    def run(self):
        while True:
            if self.stopped():
                break
            # waiting for update signal from DR (to receive the stock quote)
            with self.ticker_condition:
                self.ticker_condition.wait()
            update_time = datetime.now()
            quote = self.input_queue.get(timeout=1)
            #print(f"Ticker received quote {quote} for symbol {self.symbol}", flush=True)
            # waiting for update signal from the main thread (scheduler) about timeframe flips
            with self.TF_condition:
                self.TF_condition.wait()
            self.update(quote, update_time.timestamp())
            print(f"Ticker {self.symbol} updated at {update_time}", flush=True)
            dumpstr = f"Ticker {self.symbol} candles: "
            for t in self.candles:
                dumpstr += f"{t}:"
                for c in self.candles[t]:
                    dumpstr += f"{c} "
                dumpstr += "\n"
            print(dumpstr, flush=True)
            self.lastUpdated = update_time
            # TODO: iterate over strategies, update AS that involve flipped TFs, check triggers, and, if triggered, issue signals to broker
            for s in self.strategies:
                status = s.checkScore(self.candles)
                # TODO: change the status of the ticker
            # for now, just send the symbol to the broker
            self.output_queue.put(self.symbol)
            with self.broker_condition:
                self.broker_condition.notify()
        return

    def update(self, quote, timestamp):
        # TODO: description
        # update close prices (for live candles from the ticker) using the market price
        self.updateClose(quote)
        # update (if necessary) high and low of live candles
        self.updateHighLow(quote)
        # create new candles (if necessary; based on the current timeframe)
        self.createCandle(quote, timestamp)

    def createCandle (self, price, timestamp):
        # Insert new candle into the candle list if necessary (if timeframe is flipped)
        for tf in self.TF:
            if self.TF[tf]:
                candles = self.candles[tf]
                if candles is None:
                    continue
                prev_high = candles[0].high
                prev_low = candles[0].low
                newCandle = Candle(timestamp, price, price, price, price, prev_high, prev_low)
                candles.insert(0, newCandle)
                candles.pop()


    def updateClose(self, close_price):
        # Update close prices of live candles
        for t in self.candles.keys():
            if self.candles[t] is None:
                continue
            self.candles[t][0].close = close_price

    def updateHighLow(self, price):
        # Update high and low of live candles if necessary
        for t in self.candles.keys():
            if self.candles[t] is None:
                continue
            if price > self.candles[t][0].high:
                self.candles[t][0].high = price
            if price < self.candles[t][0].low:
                self.candles[t][0].low = price

    def initializeCandles(self, bars):
        # Initialize candles for all timeframes
        for t in self.TF:
            bars_t = bars[t]
            self.candles[t] = self.get_candle_given_data(bars_t)

    @staticmethod
    def get_candle_given_data(data):
        # Return array of 3x Candles given data (from Alpaca)
        # TODO: check that data is not empty!
        candle_list = [Candle(data[-1].timestamp, data[-1].open, data[-1].high, data[-1].low, data[-1].close, data[-2].high, data[-2].low),
                       Candle(data[-2].timestamp, data[-2].open, data[-2].high, data[-2].low, data[-2].close, data[-3].high, data[-3].low),
                       Candle(data[-3].timestamp, data[-3].open, data[-3].high, data[-3].low, data[-3].close, data[-4].high, data[-4].low)
                       ]
        return candle_list
