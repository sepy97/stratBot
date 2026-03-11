import threading
import logging
import queue
from datetime import datetime
import util
from candles import Candle
from Trade import Trade

trades_logger = logging.getLogger("trades")


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
        self.active_trades = []     # Trade objects currently open for this symbol
        self.trade_history = []     # completed Trade objects
        self.strategies = []
        self.logger = logging.getLogger("Ticker." + self.symbol)
        self.logger.debug("Ticker created: " + str(self))

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
            try:
                bar = self.input_queue.get(timeout=1)
            except queue.Empty:
                # DataRetrieval had no data for this symbol this tick — skip
                continue
            # waiting for update signal from the main thread (scheduler) about timeframe flips
            with self.TF_condition:
                self.TF_condition.wait()
            self.logger.debug("Received bar: " + str(bar))

            daily_flipped = self.TF.get('d', False)

            self.update(bar, update_time.timestamp())

            dumpstr = f"Ticker {self.symbol} has candles at time {update_time}: "
            for t in self.candles:
                dumpstr += f"{t}:"
                for c in self.candles[t]:
                    dumpstr += f"{c} "
                dumpstr += "\n"
            self.lastUpdated = update_time
            self.logger.debug(dumpstr)

            # Build chartDictNew: reverse live candle order to match BackTestStrategy indexing
            # BackTestStrategy: [-1]=current, [-2]=prev; live candles: [0]=current, [1]=prev
            chart = {
                tf: list(reversed(self.candles[tf]))
                for tf in ['d', 'w', 'm', 'q']
                if tf in self.candles and self.candles[tf] is not None
            }

            # 1. On daily candle flip: advance day count for all open trades
            if daily_flipped:
                for trade in self.active_trades:
                    trade.data['daysOpen'] += 1
                self.logger.info(
                    f"{self.symbol}: daily flip, {len(self.active_trades)} open trade(s) updated"
                )

            # 2. Re-evaluate stop each tick and tighten if possible (never widen)
            for trade in self.active_trades:
                trade.tighten_entry_stop(chart)

            # 3. Check exit conditions for all open trades against bar high/low
            closed = []
            for trade in self.active_trades:
                if trade.check_exit(bar.high, bar.low, update_time.timestamp()):
                    closed.append(trade)
                    self.trade_history.append(trade)
                    self.output_queue.put({
                        'action': 'EXIT',
                        'symbol': self.symbol,
                        'price': trade.data['exitPrice'],
                        'direction': trade.direction,
                    })
                    with self.broker_condition:
                        self.broker_condition.notify()
                    trades_logger.info(
                        f"EXIT {self.symbol}: {trade.data['stop type']} "
                        f"@ {trade.data['exitPrice']:.2f}, "
                        f"gain={trade.data['gain %']:.2f}%, "
                        f"strategy={trade.strategy.name}"
                    )
            for t in closed:
                self.active_trades.remove(t)

            # 4. Check for new entry signals (checked every update, regardless of open trades)
            if len(chart.get('d', [])) >= 2:
                for s in self.strategies:
                    if s.screenTrade(chart, None):
                        trade_list = s.getNewTrade(chart, None)
                        for t in trade_list:
                            triggerPrice, direction = t[0], t[1]
                            # Price confirmation: current bar must have actually reached the trigger level.
                            if direction == util.TickerStatus.LONG  and bar.close < triggerPrice:
                                continue
                            if direction == util.TickerStatus.SHORT and bar.close > triggerPrice:
                                continue
                            # State check — already IN for this strategy; wait for exit.
                            if any(tr.strategy is s for tr in self.active_trades):
                                continue
                            new_trade = Trade(self.symbol, triggerPrice, direction, chart, s)
                            self.active_trades.append(new_trade)
                            self.output_queue.put({
                                'action': 'ENTRY',
                                'symbol': self.symbol,
                                'price': triggerPrice,
                                'direction': direction,
                            })
                            with self.broker_condition:
                                self.broker_condition.notify()
                            trades_logger.info(
                                f"ENTRY {self.symbol} {direction.name} @ {triggerPrice}, "
                                f"stop={new_trade.stop:.2f}, RR={new_trade.data['RR']:.2f}, "
                                f"strategy={s.name}"
                            )
        return

    def update(self, bar, timestamp):
        # update close prices (for live candles from the ticker) using the market price
        self.updateClose(bar.close)
        # update high and low of live candles using the bar's actual high/low
        self.updateHighLow(bar.high, bar.low)
        # create new candles (if necessary; based on the current timeframe)
        self.createCandle(bar.close, timestamp)

    def createCandle(self, price, timestamp):
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

    def updateHighLow(self, high, low):
        # Update high and low of live candles using the bar's actual high/low
        for t in self.candles.keys():
            if self.candles[t] is None:
                continue
            if high > self.candles[t][0].high:
                self.candles[t][0].high = high
            if low < self.candles[t][0].low:
                self.candles[t][0].low = low

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
