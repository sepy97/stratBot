import threading

# TODO: add broker API to perform trades (on the paper account for now)
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
                #print(f"Broker got {symbol}", flush=True)
        return