import threading
from strategy import Strategy
import time
from datetime import datetime

class Scanner:
    def __init__(self, strategy): 
        self.symList = ["SPY", "QQQ"]
        self.strategy = strategy
        self.keepScanning = False
        self.scanThread = None

    def __str__(self):
        return "Scanner with tickers: " + self.symList
    
    def start(self, timeQuantSignal, setupList, flipDict):
        self.keepScanning = True
        self.scanThread = threading.Thread(target=self.scan, args=(timeQuantSignal, setupList, flipDict))
        self.scanThread.start()

    def stop(self):
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        print(current_time, ": Scanner: Issued stop command")
        self.keepScanning = False
        #self.scanThread.join()

    def scan(self, timeQuantSignal, setupList, flipDict):
        while self.keepScanning:
            with timeQuantSignal:
                timeQuantSignal.wait()
            if self.keepScanning:   # This is an important hack. We need to check if stop was called since Python does not support thread interrupts
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print(current_time, ": Scanner: Checking for flips")
                flipTF = [k for k, v in flipDict.items() if v]
                for TF in flipTF:
                    now = datetime.now()
                    current_time = now.strftime("%H:%M:%S")
                    print(current_time, ": Scanner: Detected flip for TF: " + TF)
                    for s in self.symList:
                        if self.strategy.isAS(s, TF):
                            setupList.append(s)
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")                
        print(current_time, ": Scanner: Finished scanning")

if __name__ == "__main__":
    strat = Strategy()
    s = Scanner(strat)
    sig = threading.Condition()
    flips = {"Y": False, "Q": False, "M": False, "W": False, "D": False, "M60": False, "M30": False, "M15": False}
    setupList = []
    #s.start(sig, setupList, flips)
    for i in range(1, 4):
        flips["Y"] = not flips["Y"]
        print("Flipping Y cont")
        with sig: 
            sig.notify()
        time.sleep(3)
    s.stop()
    with sig: 
        sig.notify()

    