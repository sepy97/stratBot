from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ProcessPoolExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.combining import AndTrigger, OrTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import ticker
import util
import session
import tzlocal
import datetime
import threading

# TODO: create class for this with watchlist of tickers, scheduler
class Updater:
    def __init__(self, TDSession):
        # TODO: description
        # TDSession is a TD Ameritrade session initiated beforehand (credentials necessary)
        # symbol is a string of the ticker symbol
        self.TDSession = TDSession
        self.symbols = util.loadSymbols()
        self.timezone = timezone="America/Los_Angeles"
        self.sched = BackgroundScheduler(daemon=False, timezone=self.timezone, executors={'threadpool': ThreadPoolExecutor(10000)}) # TODO parameterize 10000 into a (global?) variable
        self.exportSymbols()


    def run(self):
        # TODO: description
        self.sched.start(paused=True)
        # create executor for each ticker
        # schedule ticker.update() to run every 5 seconds
        #self.sched.add_job(t.update, 'interval', seconds=5, executor='threadpool')
        # later we will use a combined trigger:
        # start date should be today + 1 minute
        #start_date = '*-*-* 12:55:00' 
        #end_date = '*-*-* 12:57:00'
        self.trigger = IntervalTrigger(seconds=5, timezone=self.timezone) #AndTrigger([IntervalTrigger(seconds=5, timezone=self.timezone), CronTrigger(day_of_week='mon,tue,wed,thu,fri,sat,sun', timezone=self.timezone)])#(day_of_week='mon,tue,wed,thu,fri')])

        for s in self.symbols:
            #print ("Before addSymbol ", s, ": ", datetime.datetime.now())
            self.addSymbol(s)
            #print ("After addSymbol ", s, ": ", datetime.datetime.now())
        self.startScheduler() # or just call self.sched.resume()?

    def stop(self):
        # TODO: description
        self.sched.shutdown()

    def addSymbol(self, symbol):
        t = ticker.Ticker(symbol, self.TDSession)
        print(t.to_string())
        #print ("Scheduling ", symbol, " to start at ", self.start_date)
        #thread = threading.Thread(target=self.sched.add_job, args=(t.update, self.trigger))
        self.sched.add_job(t.update,self.trigger)

    def pauseScheduler(self):
        self.sched.pause()

    def startScheduler(self):
        self.sched.resume()

    def exportSymbols(self):
        # Function that exports all symbols to a JSON file
        print("export")