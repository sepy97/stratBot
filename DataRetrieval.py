import threading

import alpaca.data.enums
from alpaca.data import StockLatestBarRequest, TimeFrame, TimeFrameUnit
from alpaca.data.requests import StockBarsRequest
from alpaca.common.enums import Sort
from datetime import datetime

class DataRetrieval(threading.Thread):
    def __init__(self, session, watchlist, input_queue, output_queues, DR_condition, ticker_condition, *args, **kwargs):
        super(DataRetrieval, self).__init__(*args, **kwargs)
        self._stopper = threading.Event()
        self.session = session
        self.watchlist = watchlist
        self.input_queue = input_queue
        self.output_queues = output_queues
        self.DR_condition = DR_condition
        self.ticker_condition = ticker_condition

    def stopThr(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.is_set()

    def run(self):
        while True:
            if self.stopped():
                break
            with self.DR_condition:
                self.DR_condition.wait()
            self.watchlist = self.input_queue.get(timeout=1)

            request_params = StockLatestBarRequest(symbol_or_symbols=self.watchlist, timeframe=TimeFrame.Minute)
            bar = self.session.get_stock_latest_bar(request_params)

            for symbol in self.watchlist:
                self.output_queues[self.watchlist.index(symbol)].put(bar[symbol].close)
            # rewrite this loop with map
            # map(lambda s: self.output_queues[self.watchlist.index(s)].put(s), self.watchlist)
            with self.ticker_condition:
                self.ticker_condition.notify_all()
        return

    def get_initial_data(self, symbol, tfs):
        # request Stock Bars for th last 3 periods for each timeframe
        curdatetime = datetime.now()
        bars = {}
        for tf in tfs:
            match tf:
                case "m5":
                    timeframe = TimeFrame(5, TimeFrameUnit.Minute)
                case "m15":
                    timeframe = TimeFrame(15, TimeFrameUnit.Minute)
                case "m30":
                    timeframe = TimeFrame(30, TimeFrameUnit.Minute)
                case "m60":
                    timeframe = TimeFrame.Hour
                case "d":
                    return bars
                    #timeframe = TimeFrame.Day
                case "w":
                    return bars
                    #timeframe = TimeFrame.Week
                case "m":
                    return bars
                    #timeframe = TimeFrame.Month
                case "q":
                    return bars
                    #timeframe = TimeFrame(3, TimeFrameUnit.Month)
            #TODO: check if timeframe is correct
            request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, end=curdatetime, sort=Sort.DESC)
            data = self.session.get_stock_bars(request_params)[symbol]
            bars[tf] = data[-4:]

        return bars