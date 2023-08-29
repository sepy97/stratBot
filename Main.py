import threading
import util
from apscheduler.schedulers.background import BackgroundScheduler
import queue
import time

def retrieveData(input_queue, output_queues):
    print("Data retriever started", flush=True)
    # here thread should wait for items in the input_queue
    while True:
        try:
            watchlist = input_queue.get(timeout=1)
            print(f"Data retriever got {watchlist}", flush=True)
            for symbol in watchlist:
                print("Data retriever got " + symbol, flush=True)
                output_queues[watchlist.index(symbol)].put(symbol)
        except queue.Empty:
            print("Data retriever is waiting for new data", flush=True)
            pass
    return

def runBroker(input_queue):
    print("Broker started")
    while True:
        try:
            symbol = input_queue.get(timeout=1)
            print(f"Broker got {symbol}", flush=True)
        except queue.Empty:
            print("Broker is waiting for signals from strategies", flush=True)
            pass
    return

def runTicker(input_queue, output_queue):
    # TODO: initialization???
    while True:
        try:
            symbol = input_queue.get(timeout=1)
            print(f"Ticker started for {symbol}", flush=True)
            output_queue.put(symbol)
        except queue.Empty:
            print("Ticker is waiting for data from data retriever", flush=True)
            pass
    return

def scheduleDataRetrieval(symbols, output_queue):
    # append symbols to the output queue
    output_queue.put(symbols)
    print("Data retrieval scheduled", flush=True)
    return

# entry point for the program
if __name__ == '__main__':

    # TODO: override the class Thread and add a stop() method: https://www.geeksforgeeks.org/python-different-ways-to-kill-a-thread/

    # load watchlist from config file
    #watchlist = util.loadSymbols()
    watchlist = ["QQQ", "SQQQ", "TSLA", "TSLQ"]

    # create global queues for scheduled data retrieval, for data of tickers, and for signals to broker
    DR_queue = queue.Queue()
    ticker_queues = []
    for t in watchlist:
        ticker_queues.append(queue.Queue())
    broker_queue = queue.Queue()

    # authorize data retriever
    data_retriever = threading.Thread(target=retrieveData, args=(DR_queue, ticker_queues), daemon=True)
    # data_retriever should send data (via map) to ticker threads
    data_retriever.start()

    # authorize broker
    broker = threading.Thread(target=runBroker, args=(broker_queue,), daemon=True)
    # broker should wait for signals from ticker threads
    broker.start()

    # get tickers from watchlist, create an iterable collection of threads, and start threads for each ticker
    tickers = []
    for symbol in watchlist:
        tickers.append(threading.Thread(target=runTicker, args=(ticker_queues[watchlist.index(symbol)], broker_queue), daemon=True))
    for t in tickers:
        # each thread should first initialize the ticker, then start waiting for the signal from the data retriever
        t.start()

    # create global APScheduler and schedule data retrieval (by function that adds signal to the queue) every 5 seconds
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda:scheduleDataRetrieval(watchlist, DR_queue), 'interval', seconds=5, timezone="America/Los_Angeles")
    scheduler.start()

    time.sleep(10)

    # finish all threads while saving the state of the program
    data_retriever.join()
    broker.join()
    # export the watchlist
    #util.exportWatchlist()
    for t in tickers:
        # save the state of each ticker?
        t.join()
    scheduler.shutdown()





if False:

    # Import the client
    #from td.client import TDClient
    import datetime
    import time
    import ticker
    import session
    import updater
    import util

    from concurrent.futures import ThreadPoolExecutor
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    # Create a new session, credentials path is required.
    TDSession = session.initTDSession()

    # Init all tickers from the watchlist saved in config file
    list_of_tickers = util.loadSymbols()
    watchlist = dict(map(lambda t: (t, ticker.Ticker(t, TDSession)), list_of_tickers))

    # Schedule tickers update to run every 5 seconds

    executor = ThreadPoolExecutor()

    scheduler = BackgroundScheduler()
    scheduler.start()
    #for t in watchlist:
    #    scheduler.add_job(watchlist[t].update, executors = {'threadpoolexec',executor}, trigger=IntervalTrigger(seconds=5, timezone="America/Los_Angeles"), id = t)


    u = updater.Updater(TDSession)
    u.loadStrategy("Bullish reversal 2-2")
    u.run()
    time.sleep(6)#*60)
    u.addSymbol("QQQ")
    u.addSymbol("SQQQ")
    u.addSymbol("TSLQ") # TSLA inverse -- got an error; probably, because not enough data for yearly/quarterly period
    u.addSymbol("TSLA")
    time.sleep(8*60*60) # just for hawaii
    u.stop()
    print("Updater is done!\nMoving logs...")
    util.moveLogs()
    print("Finished!")
    time.sleep(1)

