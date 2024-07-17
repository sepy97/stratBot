import threading
from apscheduler.schedulers.background import BackgroundScheduler
import queue
import time
import alpaca_chart

from datetime import datetime, timedelta

import util
from Broker import Broker
from DataRetrieval import DataRetrieval
from Ticker import Ticker
from strategy import Strategy
import session

def scheduling(symbols, DR_queue, DR_condition, TF, TF_condition, opening_time, time_quant=5):
    current_time = datetime.now()
    DR_queue.put(symbols)
    with DR_condition:
        DR_condition.notify()
    #print("Data retrieval signal sent", flush=True)
    for t in TF:
        TF[t] = False
        if candle_flipped := util.detectTFFlip(current_time, util.timeframe_LUT[t][0], time_quant):
            TF[t] = True
            print(f"Timeframe {t} flipped: {candle_flipped} at time {current_time}", flush=True)
    with TF_condition:
        TF_condition.notify_all()
    #print("Timeframe signal sent to all tickers", flush=True)
    return

# entry point for the program
if __name__ == '__main__':
    # INITIALIZATION (TODO: separate into a different script that is scheduled to run once a day by cron)
    # load watchlist from config file
    #watchlist = util.loadSymbols()
    watchlist = ["TSLA", "AAPL", "QQQ", "SQQQ"]
    session = alpaca_chart.initSession()

    # create global queues for scheduled data retrieval, for data with tickers quotes, and for signals to broker
    # each queue is used for communication between different threads
    # in the DR_queue each element is the current "watchlist"
    DR_queue = queue.Queue()
    DR_condition = threading.Condition()
    # there are multiple ticker queues, one queue for each ticker in the watchlist
    ticker_queues = []
    ticker_condition = threading.Condition()
    for t in watchlist:
        # each element of the ticker queue is the current (for the time period) price that DR receives
        ticker_queues.append(queue.Queue())
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
    for symbol in watchlist:
        t = Ticker(symbol, ticker_queues[watchlist.index(symbol)], TF, broker_queue, ticker_condition, TF_condition, broker_condition, daemon=True)
        strategies = util.loadStrategies()
        for s in strategies:
            strategy = Strategy()
            strategy.stratFromDict(s)
            t.strategies.append(strategy)
        #t.strategies.append(Strategy())
        data = data_retriever.get_initial_data(symbol, ["m5", "m15", "m30", "m60", "d", "w", "m", "q"])
        t.initializeCandles(data)
        tickers.append(t)
    for t in tickers:
        # each thread should first initialize the ticker, then start waiting for the signal from the data retriever
        t.start()

    # create global APScheduler and schedule data retrieval (by function that adds signal to the queue) every 5 seconds
    scheduler = BackgroundScheduler()
    proper_start_time = util.getProperStartTime(datetime.now(), time_quant)
    print(f"Proper start time: {proper_start_time}")
    print(f"Opening time: {datetime.fromtimestamp(util.getTodayOpenTime_ms()//1000)}")
    scheduler.add_job(lambda:scheduling(watchlist, DR_queue, DR_condition, TF, TF_condition, time_quant), 'interval', seconds=5, timezone="America/Los_Angeles", start_date=proper_start_time)
    scheduler.start()

    time.sleep(6000)

    # finish all threads while saving the state of the program
    data_retriever.stopThr()
    broker.stopThr()
    # export the watchlist
    #util.exportWatchlist()
    for t in tickers:
        # save the state of each ticker?
        t.stopThr()

    print ("FINISHING the scheduler!")
    scheduler.shutdown(wait=False)