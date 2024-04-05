# This class issues signal every time quant and updates its internal field tracking all major flips (15min, 30min, 1Hr, D, W, M, Q, Y)
# TODO: How to expose candle flip variable? 
# TODO: Make it singleton object
import threading
import time
from datetime import datetime

TIME_QUANT_SEC = 5  # minimum quantum of time over which we refresh 

class MainClock:
    def __init__(self): 
        self.candleFlipped = {"Y": False, "Q": False, "M": False, "W": False, "D": False, "M60": False, "M30": False, "M15": False}
        self.internalStopEvent = True

    def __str__(self):
        return "MainClock, time is " + datetime.now()
    
    def startClock(self, stop_event):
        self.internalStopEvent = False
        self.timeQuantAlert = threading.Condition()
        #self.candleFlipAlert = threading.Condition()
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        print(current_time, ": Starting clock")
        self.scheduleAlert(stop_event)
        #return (self.timeQuantAlert, self.candleFlipAlert)
        return self.timeQuantAlert

    def scheduleAlert(self, stop_event):
        if not stop_event.is_set() and not self.internalStopEvent:  # TODO: ideally this should be done via some sort of interrupt (like exception) otherwise this won't exit as soon as event is set
            # Update flips if needed
            self.checkCandleFlips()
            # Issue signal that time quant is over
            with self.timeQuantAlert:
                self.timeQuantAlert.notify_all()
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print(current_time, ": Issued regular time quant alert")
            # Schedule next iteration
            threading.Timer(TIME_QUANT_SEC, self.scheduleAlert, args=(stop_event, )).start()  # Schedule the next execution after TIME_QUANT_SEC seconds
        else:
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print(current_time, ": No more updates scheduled")
        return
    
    def stopClock(self):
        with self.timeQuantAlert:
            self.timeQuantAlert.notify_all()
        self.internalStopEvent = True
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        print(current_time, ": Stopping clock via internal call")
        return 
    
    # TODO: check if this time corresponds to new candle, i.e. previous time quant belongs to different candle than current time quant: 
    # (Time - Time_Quant) % AGGREGATION_TIME < Time % AGGREGATION_TIME <-- need to check if this is sufficient
    def checkCandleFlips(self):
        self.candleFlipped["Y"] = False


if __name__ == "__main__":
    stop_event = threading.Event()
    stop_event.clear()
    m = MainClock()
    m.startClock(stop_event)
    time.sleep(10)
    m.stopClock()
    time.sleep(1)
    m.startClock(stop_event)
    time.sleep(6)
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print(current_time, ": Setting stop event from Main")
    stop_event.set()