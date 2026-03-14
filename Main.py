import threading
import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
import queue
import time
import pandas as pd
from alpaca.data import StockHistoricalDataClient

from datetime import datetime, timedelta

import util
from alpaca_config import alpaca_config
import MarketTimeManager as mtm
from Broker import Broker
from DataRetrieval import DataRetrieval
from Ticker import Ticker
from strategy import Strategy
from BackTester import printTradeDict
import log_functions

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")

def scheduling(symbols, DR_queue, DR_condition, TF, TF_condition, market_time_manager, time_quant=5):
    current_time = datetime.now()
    DR_queue.put(symbols)
    with DR_condition:
        DR_condition.notify()
    #print("Data retrieval signal sent", flush=True)
    for t in TF:
        TF[t] = False
        if candle_flipped := market_time_manager.detectTFFlip(current_time, mtm.timeframe_LUT[t][0], time_quant):
            TF[t] = True
            print(f"Timeframe {t} flipped: {candle_flipped} at time {current_time}", flush=True)
    with TF_condition:
        TF_condition.notify_all()
    #print("Timeframe signal sent to all tickers", flush=True)
    return

def log_session_summary(tickers):
    """Log performance statistics for all closed trades in the session."""
    all_closed = [trade for t in tickers for trade in t.trade_history]
    if not all_closed:
        trades_logger.info("Session summary: no closed trades.")
        return

    total = len(all_closed)
    pnl_values = [tr.realized_pnl() for tr in all_closed]
    start_values = [tr.starting_value() for tr in all_closed]
    wins = sum(1 for pnl in pnl_values if pnl is not None and pnl > 0)
    total_pnl = sum(pnl for pnl in pnl_values if pnl is not None)
    total_start = sum(start_values)
    total_gain_pct = 100 * total_pnl / total_start if total_start else 0

    by_strategy = {}
    for tr in all_closed:
        name = tr.strategy.name
        by_strategy.setdefault(name, []).append(tr)

    lines = [
        "========================",
        f"  Session summary:",
        f"  Total trades : {total}",
        f"  Win rate     : {100 * wins / total:.1f}%  ({wins}/{total})",
        f"  Total PnL    : ${total_pnl:.2f}",
        f"  Total gain   : {total_gain_pct:.2f}%",
    ]
    for strat_name, trades in by_strategy.items():
        s_total = len(trades)
        s_pnl_values = [tr.realized_pnl() for tr in trades]
        s_start_values = [tr.starting_value() for tr in trades]
        s_wins = sum(1 for pnl in s_pnl_values if pnl is not None and pnl > 0)
        s_pnl = sum(pnl for pnl in s_pnl_values if pnl is not None)
        s_start = sum(s_start_values)
        s_gain_pct = 100 * s_pnl / s_start if s_start else 0
        lines.append(
            f"  [{strat_name}] trades={s_total}, "
            f"wins={s_wins} ({100 * s_wins / s_total:.1f}%), "
            f"pnl=${s_pnl:.2f}, gain={s_gain_pct:.2f}%"
        )
    lines.append("========================")
    summary = "\n".join(lines)
    trades_logger.info(summary)

# entry point for the program
if __name__ == '__main__':
    # INITIALIZATION (TODO: separate into a different script that is scheduled to run once a day by cron)

    # Set up unified logging (routes all loggers to live_trading.log + console + per-ticker strat_<symbol>.log)
    log_queue, log_proc = log_functions.start_logging_process(log_functions.log_init("live_trading.log"))

    # Route uncaught thread exceptions through the logging system instead of stderr
    def _thread_excepthook(args):
        logger.error(
            "Uncaught exception in thread '%s'",
            args.thread.name if args.thread else '<unknown>',
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    threading.excepthook = _thread_excepthook

    try:
        # load watchlist from csv (same file used by backtester)
        watchlist = pd.read_csv('Watchlists/NASDAQ100_2025.csv', header=None)[0].to_list()
        session = StockHistoricalDataClient(alpaca_config['key'], alpaca_config['secret_key'])
        market_time_manager = mtm.MarketTimeManager()


        # create global queues for scheduled data retrieval, for data with tickers quotes, and for signals to broker
        # each queue is used for communication between different threads
        # in the DR_queue each element is the current "watchlist"
        DR_queue = queue.Queue()
        DR_condition = threading.Condition()
        # there are multiple ticker queues, one queue for each ticker in the watchlist
        ticker_queues = {symbol: queue.Queue() for symbol in watchlist}
        ticker_condition = threading.Condition()
        # broker queue contains symbols that should be traded
        broker_queue = queue.Queue()
        broker_condition = threading.Condition()
        # TF is a dictionary of timeframes and boolean values that indicate if the timeframe is flipped; initialized by True for all timeframes
        TF = {"m5": True, "m15": True, "m30": True, "m60": True, "d": True, "w": True, "m": True, "q": True}
        TF_condition = threading.Condition()
        time_quant = 5 # interval (in seconds) before the next data retrieval and trigger checks

        # authorize data retriever
        data_retriever = DataRetrieval(session, watchlist, DR_queue, ticker_queues, DR_condition, ticker_condition, daemon=True)
        # data_retriever should send data (via map) to ticker threads
        data_retriever.start()

        # authorize broker
        broker = Broker(broker_queue, broker_condition, daemon=True)
        # broker should wait for signals from ticker threads
        broker.start()

        # get tickers from watchlist, create an iterable collection of threads, and start threads for each ticker
        tickers = []
        valid_watchlist = []
        for symbol in watchlist:
            data = data_retriever.get_initial_data(symbol, ["m5", "m15", "m30", "m60", "d", "w", "m", "q"])
            if data is None:
                continue
            t = Ticker(symbol, ticker_queues[symbol], TF, broker_queue, ticker_condition, TF_condition, broker_condition, daemon=True)
            t.strategies.append(Strategy("BasicDailyAS"))
            t.strategies.append(Strategy("StratLab2dGM"))
            t.initializeCandles(data)
            tickers.append(t)
            valid_watchlist.append(symbol)
        print(f"Initialized {len(valid_watchlist)}/{len(watchlist)} symbols successfully.")
        for t in tickers:
            # each thread should first initialize the ticker, then start waiting for the signal from the data retriever
            t.start()

        # create global APScheduler and schedule data retrieval (by function that adds signal to the queue) every 5 seconds
        scheduler = BackgroundScheduler()
        proper_start_time = market_time_manager.getProperStartTime(datetime.now(), time_quant)
        print(f"Proper start time: {proper_start_time}")
        print(f"Opening time: {datetime.fromtimestamp(market_time_manager.getTodayOpenTime())}")
        scheduler.add_job(lambda:scheduling(valid_watchlist, DR_queue, DR_condition, TF, TF_condition, market_time_manager, time_quant), 'interval', seconds=5, timezone="America/Los_Angeles", start_date=proper_start_time)
        scheduler.start()

        time.sleep(6 * 60 * 60) # 6 hours in seconds

        # Stop the scheduler first so no new ticks can fire during shutdown.
        # Must happen before force-closing trades to avoid the race where a
        # mid-flight tick sees an empty active_trades and re-enters a position.
        scheduler.shutdown(wait=True)

        # finish all threads while saving the state of the program
        data_retriever.stopThr()
        for t in tickers:
            t.stopThr()

        # force-close any trades still open at shutdown
        now = time.time()
        for t in tickers:
            if not t.active_trades:
                continue
            # use last known m5 close as the exit price, fall back to 'd'
            last_price = None
            for tf in ('m5', 'm15', 'd'):
                if t.candles.get(tf):
                    last_price = t.candles[tf][0].close
                    break
            if last_price is None:
                logger.warning(
                    f"Cannot force-close {t.symbol}: no candle data available, "
                    f"{len(t.active_trades)} trade(s) left open in CSV"
                )
                continue
            for trade in list(t.active_trades):
                trade.force_close(last_price, now)
                t.trade_history.append(trade)
                t.active_trades.remove(trade)
                broker_queue.put({
                    'action': 'EXIT',
                    'symbol': t.symbol,
                    'price': trade.data['exitPrice'],
                    'direction': trade.direction,
                })
                with broker_condition:
                    broker_condition.notify()
                print(f"Forced close: {t.symbol} @ {last_price:.2f} (gain={trade.data['gain %']:.2f}%)")
                trades_logger.info(
                    f"EXIT {t.symbol}: forced close @ {last_price:.2f}, "
                    f"gain={trade.data['gain %']:.2f}%, "
                    f"strategy={trade.strategy.name}"
                )

        broker.stopThr()
        log_session_summary(tickers)
        # export all trades (completed + still-open) to CSV
        all_trades = {
            t.symbol: [trade.data for trade in t.trade_history + t.active_trades]
            for t in tickers
        }
        if any(all_trades.values()):
            os.makedirs("Trades", exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            printTradeDict(all_trades, f"Trades/live_trades_{ts}.csv")
        print("Moving logs...")
        util.moveLogs()
    except Exception:
        logger.exception("Fatal error in main process")
        raise
    finally:
        log_functions.stop_logging_process(log_queue, log_proc)