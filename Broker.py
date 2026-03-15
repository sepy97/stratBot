import threading
import logging

import log_functions
logger = logging.getLogger(log_functions.CHANNEL_BROKER)


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
                order = self.input_queue.get(timeout=1)
                action    = order.get('action', '')
                symbol    = order.get('symbol', '')
                price     = order.get('price', 0)
                direction = order.get('direction')
                dir_name  = direction.name if direction else ''
                # TODO: place actual Alpaca paper-account order here
                logger.info(f"Broker: {action} {symbol} {dir_name} @ {price}")
        return
