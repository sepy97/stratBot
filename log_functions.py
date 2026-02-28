import logging
import logging.handlers
import multiprocessing as mp
import sys
from time import sleep

class SimpleQueueHandler(logging.Handler):
    """A QueueHandler that works with mp.SimpleQueue."""
    def __init__(self, queue: mp.SimpleQueue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        try:
            self.queue.put(record)
        except Exception:
            self.handleError(record)

def log_init(log_file="strat_bot.log"):
    """
    Returns a pure config object (picklable) used by the logging process
    to construct handlers. Avoids passing actual handler objects across 
    processes, which is unsafe.
    """
    return {
        "log_file": log_file,
        "console_level": logging.INFO,
        "file_level": logging.DEBUG,
        "fmt": "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }

def _logging_process_main(log_queue: mp.SimpleQueue, config: dict):
    """
    Dedicated logging process that receives LogRecords from all workers
    and the main process and writes them to console + file using the
    formatting defined in config.
    """

    # Rebuild handlers inside THIS process
    console_handler = logging.StreamHandler()
    console_handler.setLevel(config["console_level"])

    file_handler = logging.FileHandler(config["log_file"], mode='w')
    file_handler.setLevel(config["file_level"])

    formatter = logging.Formatter(config["fmt"], config["datefmt"])
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [console_handler, file_handler]
    root.setLevel(logging.DEBUG)

    while True:
        try:
            record = log_queue.get()  # block until record
        except (EOFError, OSError):
            # If the queue is broken in some way, break out and exit gracefully
            break
        if record is None:
            break
        # If we receive a LogRecord, handle it
        try:
            # NOTE: record is already a LogRecord instance sent via QueueHandler
            root.handle(record)
        except Exception:
            # Avoid crashing the logging process: print exception and continue
            import traceback
            traceback.print_exc()


    # Clean exit
    try:
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
    except Exception:
        pass

def start_logging_process(config):
    """
    Creates log_queue and starts the logging process.
    Also configures the main process root logger to send all logs to queue.
    """
    log_queue = mp.SimpleQueue()

    # Main process logger -> queue
    #queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler = SimpleQueueHandler(log_queue)
    root = logging.getLogger()
    root.handlers = [queue_handler]
    root.setLevel(logging.DEBUG)

    # Dedicated logging process
    log_proc = mp.Process(
        target=_logging_process_main,
        args=(log_queue, config),
        daemon=True
    )
    log_proc.start()

    return log_queue, log_proc

def stop_logging_process(log_queue: mp.SimpleQueue, log_proc: mp.Process, timeout: float = 5.0):
    """
    Stop the logging process by sending sentinel and joining it.
    If it doesn't exit within `timeout` seconds, terminate it.
    """
    try:
        # send sentinel to stop the logging process
        log_queue.put(None)
    except Exception:
        pass

    # wait for graceful exit
    log_proc.join(timeout)
    if log_proc.is_alive():
        try:
            log_proc.terminate()
        except Exception:
            pass
        log_proc.join(1.0)


def subprocess_init(log_queue: mp.SimpleQueue) -> None:
    #h = logging.handlers.QueueHandler(log_queue)
    h = SimpleQueueHandler(log_queue)
    logger = logging.getLogger()
    logger.handlers = [h]  # Replace all handlers with the queue handler
    logger.setLevel(logging.DEBUG)

# ====== Example usage ====== TODO: this needs to be rewritten to accommodate new implmementation ======
def _init_pool(log_queue):
    subprocess_init(log_queue)

def _worker(symbol):
    logger = logging.getLogger(__name__)
    logger.debug("Debug message")
    logger.info("Info message for symbol %s", symbol)
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")
    sleep(1)
    logger.info("Worker finished. Symbol: %s", symbol)
    return 42

if __name__ == "__main__":
    log_queue, listener = log_init("test_log.log")
    listener.start()
    for h in logging.getLogger().handlers:
        print(h, h.level)
    logger = logging.getLogger(__name__)
    logger.info("Main process starting")
    logger.debug("Debug message from main process")
    symbol_valid = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
    with mp.Pool(processes=4, initializer=_init_pool, initargs=(log_queue, )) as pool:
            total_result = pool.starmap(_worker, [(sym, ) for sym in symbol_valid])  
    sleep(1)
    logger.info("Main process finished")
    logger.debug("Debug message from main process before stopping listener")
    listener.stop()