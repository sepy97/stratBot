from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ProcessPoolExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.combining import AndTrigger, OrTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import ticker
import util
import strategy
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
        self.strategy = None #strategy.Strategy()
        self.scheduled_jobs = []

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
        # Look for the symbol in the config file (where we store the watchlist)
        watchlist_from_file = util.tomlkit.loads(util.Path("config.toml").read_text())
        found = False
        for element in watchlist_from_file["watchlist"]:
            if element["symbol"] == symbol:
                found = True
                break
        if not found:
            symbol_item = util.tomlkit.item({'symbol': symbol})
            watchlist_AOT = util.tomlkit.aot()
            watchlist_AOT.append(symbol_item)
            watchlist_from_file.append("watchlist", watchlist_AOT)
            util.Path("config.toml").write_text(util.tomlkit.dumps(watchlist_from_file))
            self.symbols.append(symbol)

        # Look for the scheduled job for that symbol
        if symbol in self.scheduled_jobs:
            print("Job for symbol ", symbol, " is already scheduled")
        else:
            t = ticker.Ticker(symbol, self.TDSession)
            self.sched.add_job(lambda:t.update(self.strategy), self.trigger, id=symbol)
            self.scheduled_jobs.append(symbol)

    def pauseScheduler(self):
        self.sched.pause()

    def startScheduler(self):
        self.sched.resume()

    def loadStrategy(self, name):
        strat_dic = util.tomlkit.loads(util.Path("config.toml").read_text())["strategies"]
        for element in strat_dic:
            if element["name"] == name:
                self.strategy = strategy.Strategy(name, element["type"], element["patterns"], element["tfc"], element["exit"])
                return True
        print("Strategy not found")
