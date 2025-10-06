import logging
import logging.handlers
import multiprocessing as mp
import sys
from time import sleep

def log_init(log_file="strat_bot.log") -> tuple[mp.Queue, logging.handlers.QueueListener]:
    log_queue = mp.Queue()

    # --- 2. Define handlers for console and file ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)   # show only INFO and above

    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)     # capture everything

    # --- 3. Define a formatter ---
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    # --- 4. Set up a listener that uses both handlers ---
    listener = logging.handlers.QueueListener(log_queue, console_handler, file_handler)

    # --- 5. Configure root logger to send logs into the queue ---
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # global minimum threshold
    root_logger.addHandler(queue_handler)

    return log_queue, listener

def subprocess_init(log_queue: mp.Queue) -> None:
    h = logging.handlers.QueueHandler(log_queue)
    logger = logging.getLogger()
    logger.handlers = []  # Remove all other handlers
    logger.addHandler(h)
    logger.setLevel(logging.DEBUG)

# ====== Example usage ======
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
    logger = logging.getLogger(__name__)
    logger.info("Main process starting")
    symbol_valid = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
    with mp.Pool(processes=4, initializer=_init_pool, initargs=(log_queue, )) as pool:
            total_result = pool.starmap(_worker, [(sym, ) for sym in symbol_valid])  

    listener.stop()