import threading
import logging
import queue

import alpaca.data.enums
from alpaca.data import StockLatestBarRequest, TimeFrame, TimeFrameUnit
from alpaca.data.requests import StockBarsRequest
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
import log_functions
market_logger = logging.getLogger(log_functions.CHANNEL_MARKET)

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
            # waiting for the signal from the main thread (scheduler)
            with self.DR_condition:
                self.DR_condition.wait()
            try:
                self.watchlist = self.input_queue.get(timeout=1)
            except queue.Empty:
                logger.warning("DataRetrieval: watchlist queue empty after notify, skipping tick")
                continue
            # API request with retry on connection errors
            request_params = StockLatestBarRequest(symbol_or_symbols=self.watchlist, feed=None)
            bar = None
            for attempt in range(3):
                try:
                    bar = self.session.get_stock_latest_bar(request_params)
                    break
                except Exception as e:
                    logger.warning(f"DataRetrieval: get_stock_latest_bar attempt {attempt + 1} failed: {e}")
                    if attempt == 2:
                        logger.error("DataRetrieval: all retries exhausted, skipping this tick")
            if bar is None:
                continue
            # for now, bar data is being put into the output queues in a for-loop
            # TODO: Use map function to put bar data into output queues
            distributed = 0
            for symbol in self.watchlist:
                if symbol not in bar:
                    logger.warning(f"DataRetrieval: no bar returned for {symbol} this tick, skipping")
                    continue
                self.output_queues[symbol].put(bar[symbol])
                distributed += 1
            # map(lambda s: self.output_queues[self.watchlist.index(s)].put(s), self.watchlist)
            market_logger.debug(f"Tick: bar distributed to {distributed}/{len(self.watchlist)} symbols")
            with self.ticker_condition:
                self.ticker_condition.notify_all()
        return

    def get_initial_data(self, symbol, tfs):
        # request Stock Bars for the last 3 periods for each timeframe
        # Returns None if data is unavailable for any timeframe (symbol will be skipped by caller)
        curdatetime = datetime.now()
        bars = {}
        for tf in tfs:
            match tf:
                case "m5":
                    timeframe = TimeFrame(5, TimeFrameUnit.Minute)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5)
                case "m15":
                    timeframe = TimeFrame(15, TimeFrameUnit.Minute)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5)
                case "m30":
                    timeframe = TimeFrame(30, TimeFrameUnit.Minute)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5)
                case "m60":
                    timeframe = TimeFrame(1, TimeFrameUnit.Hour)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5)
                case "d":
                    timeframe = TimeFrame(1, TimeFrameUnit.Day)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=10) # 10 days (including weekends) ago
                    # TODO: detect last trading day and adjust startdate accordingly 5 days from the last trading day)
                case "w":
                    timeframe = TimeFrame(1, TimeFrameUnit.Week)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5*7) # 5 weeks ago
                case "m":
                    timeframe = TimeFrame(1, TimeFrameUnit.Month)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5*30) # 5 months ago
                case "q":
                    timeframe = TimeFrame(3, TimeFrameUnit.Month)
                    enddate = curdatetime
                    startdate = curdatetime - timedelta(days=5*90) # 5 quarters ago
                case _:
                    raise ValueError(f"Unknown timeframe: {tf}")
            try:
                request_params = StockBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, start=startdate, end=enddate, limit=None, adjustment=None, feed=None)
                response = self.session.get_stock_bars(request_params)
                data = response[symbol]
                if data is None or len(data) < 4:
                    logger.warning(f"Insufficient bar data for {symbol} at timeframe {tf} (got {len(data) if data else 0} bars, need 4). Skipping symbol.")
                    return None
            except Exception as e:
                logger.warning(f"Failed to get bar data for {symbol} at timeframe {tf}: {e}. Skipping symbol.")
                return None
            bars[tf] = data[-4:]

        return bars