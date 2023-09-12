import threading
import util
from apscheduler.schedulers.background import BackgroundScheduler
import queue
import time


class DataRetrieval(threading.Thread):
    def __init__(self, watchlist, input_queue, output_queues, DR_condition, ticker_condition, *args, **kwargs):
        super(DataRetrieval, self).__init__(*args, **kwargs)
        self._stopper = threading.Event()
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
            print(f"Data retriever got {self.watchlist}", flush=True)
            for symbol in self.watchlist:
                print("Data retriever got " + symbol, flush=True)
                self.output_queues[self.watchlist.index(symbol)].put(symbol)
            with self.ticker_condition:
                self.ticker_condition.notify_all()
        return

class Broker(threading.Thread):
    def __init__(self, input_queue, broker_condition, *args, **kwargs):
        super(Broker, self).__init__(*args, **kwargs)
        self._stopper = threading.Event()
        self.input_queue = input_queue
        self.broker_condition = broker_condition

    def stopThr(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.is_set()

    def run(self):
        while True:
            if self.stopped():
                break
            with self.broker_condition:
                self.broker_condition.wait()
            while not self.input_queue.empty():
                symbol = self.input_queue.get(timeout=1)
                print(f"Broker got {symbol}", flush=True)
        return

class Ticker(threading.Thread):
        def __init__(self, input_queue, output_queue, ticker_condition, broker_condition, *args, **kwargs):
            super(Ticker, self).__init__(*args, **kwargs)
            self._stopper = threading.Event()
            self.input_queue = input_queue
            self.output_queue = output_queue
            self.ticker_condition = ticker_condition
            self.broker_condition = broker_condition

        def stopThr(self):
            self._stopper.set()

        def stopped(self):
            return self._stopper.is_set()

        def run(self):
            while True:
                if self.stopped():
                    break
                with self.ticker_condition:
                    self.ticker_condition.wait()
                symbol = self.input_queue.get(timeout=1)
                print(f"Ticker started for {symbol}", flush=True)
                self.output_queue.put(symbol)
                with self.broker_condition:
                    self.broker_condition.notify()
            return


def scheduleDataRetrieval(symbols, output_queue, DR_condition):
    # append symbols to the output queue
    output_queue.put(symbols)
    print("Data retrieval scheduled", flush=True)
    with DR_condition:
        DR_condition.notify()
    return

# entry point for the program
if __name__ == '__main__':

    # TODO: override the class Thread and add a stop() method: https://www.geeksforgeeks.org/python-different-ways-to-kill-a-thread/

    # load watchlist from config file
    #watchlist = util.loadSymbols()
    watchlist = ["QQQ", "SQQQ", "TSLA", "TSLQ"]

    # create global queues for scheduled data retrieval, for data of tickers, and for signals to broker
    DR_queue = queue.Queue()
    DR_condition = threading.Condition()
    ticker_queues = []
    ticker_condition = threading.Condition()
    for t in watchlist:
        ticker_queues.append(queue.Queue())
    broker_queue = queue.Queue()
    broker_condition = threading.Condition()

    # authorize data retriever
    data_retriever = DataRetrieval(watchlist, DR_queue, ticker_queues, DR_condition, ticker_condition, daemon=True)
    # data_retriever should send data (via map) to ticker threads
    data_retriever.start()

    # authorize broker
    broker = Broker(broker_queue, broker_condition, daemon=True)
    # broker should wait for signals from ticker threads
    broker.start()

    # get tickers from watchlist, create an iterable collection of threads, and start threads for each ticker
    tickers = []
    for symbol in watchlist:
        tickers.append(Ticker(ticker_queues[watchlist.index(symbol)], broker_queue, ticker_condition, broker_condition, daemon=True))
    for t in tickers:
        # each thread should first initialize the ticker, then start waiting for the signal from the data retriever
        t.start()

    # create global APScheduler and schedule data retrieval (by function that adds signal to the queue) every 5 seconds
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda:scheduleDataRetrieval(watchlist, DR_queue, DR_condition), 'interval', seconds=5, timezone="America/Los_Angeles")
    scheduler.start()

    time.sleep(60)

    # finish all threads while saving the state of the program
    data_retriever.stopThr()
    #data_retriever.join()
    broker.stopThr()
    #broker.join()
    # export the watchlist
    #util.exportWatchlist()
    for t in tickers:
        # save the state of each ticker?
        t.stopThr()
        #t.join()

    print ("FINISHING the scheduler!")
    scheduler.shutdown(wait=False)





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

