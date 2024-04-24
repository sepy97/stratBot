import MainClock
import threading
import time
from datetime import datetime
import Scanner
import strategy

stop_event = threading.Event()
stop_event.clear()
m = MainClock.MainClock()
strat = strategy.Strategy()
timeQuantSignal = m.getTimeQuantAlert()
scanner = Scanner.Scanner(strat)
setupList = []

scanner.start(timeQuantSignal, setupList, m.candleFlipped) # scan for setups on timeQuantSignal notification and update setupList
m.startClock(stop_event)
time.sleep(6)

scanner.stop()
#stop_event.set()
now = datetime.now()
current_time = now.strftime("%H:%M:%S")
print(current_time, "Main thread: Stopping clock")
m.stopClock()
#now = datetime.now()
#current_time = now.strftime("%H:%M:%S")
#print(current_time, ": Setting stop event from Main")

