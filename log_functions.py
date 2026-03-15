import json
import logging
import logging.handlers
import multiprocessing as mp
import os
import sys
from datetime import datetime as _datetime
from time import sleep

class SimpleQueueHandler(logging.Handler):
    """A QueueHandler that works with mp.SimpleQueue."""
    def __init__(self, queue: mp.SimpleQueue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        try:
            record.msg = record.getMessage()
            record.args = None
            self.queue.put(record)
        except Exception:
            self.handleError(record)

def log_init(log_file="strat_bot.log", trades_file="trades.log", log_dir="."):
    """
    Returns a pure config object (picklable) used by the logging process
    to construct handlers. Avoids passing actual handler objects across
    processes, which is unsafe.

    log_dir defaults to "." for backward compatibility with existing callers
    that don't pass it. Pass log_dir to write all files into a specific directory
    (e.g. the iCloud shared path).
    """
    return {
        "log_file":     os.path.join(log_dir, log_file),
        "trades_file":  os.path.join(log_dir, trades_file),
        "system_file":  os.path.join(log_dir, "system.log"),
        "market_file":  os.path.join(log_dir, "market.log"),
        "broker_file":  os.path.join(log_dir, "broker.log"),
        "ledger_file":  os.path.join(log_dir, "events.jsonl"),
        "log_dir":      log_dir,
        "console_level": logging.INFO,
        "file_level":    logging.DEBUG,
        "fmt":     "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s",
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

    # Domain-specific channel handlers
    trades_handler = logging.FileHandler(config["trades_file"], mode='w')
    trades_handler.setFormatter(formatter)
    trades_handler.setLevel(logging.DEBUG)

    system_handler = logging.FileHandler(config["system_file"], mode='w')
    system_handler.setFormatter(formatter)
    system_handler.setLevel(logging.DEBUG)

    market_handler = logging.FileHandler(config["market_file"], mode='w')
    market_handler.setFormatter(formatter)
    market_handler.setLevel(logging.DEBUG)

    broker_handler = logging.FileHandler(config["broker_file"], mode='w')
    broker_handler.setFormatter(formatter)
    broker_handler.setLevel(logging.DEBUG)

    # Ledger uses a bare formatter — JSON lines already contain timestamps
    ledger_formatter = logging.Formatter("%(message)s")
    ledger_handler = logging.FileHandler(config["ledger_file"], mode='a')
    ledger_handler.setFormatter(ledger_formatter)
    ledger_handler.setLevel(logging.DEBUG)

    ticker_handlers: dict = {}  # symbol -> FileHandler for per-ticker log files

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
            # Route to domain-specific channel files
            if record.name == "trades":
                trades_handler.emit(record)
            if record.name == "system":
                system_handler.emit(record)
            if record.name == "market":
                market_handler.emit(record)
            if record.name == "broker":
                broker_handler.emit(record)
            if record.name == "ledger":
                ledger_handler.emit(record)
            # Route Ticker.<symbol> loggers to per-ticker files
            if record.name.startswith("Ticker."):
                symbol = record.name.split(".", 1)[1]
                if symbol not in ticker_handlers:
                    h = logging.FileHandler(
                        os.path.join(config["log_dir"], f"strat_{symbol}.log"), mode='a')
                    h.setFormatter(formatter)
                    h.setLevel(logging.DEBUG)
                    ticker_handlers[symbol] = h
                ticker_handlers[symbol].emit(record)
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
    for h in [trades_handler, system_handler, market_handler, broker_handler, ledger_handler]:
        try:
            h.close()
        except Exception:
            pass
    for h in ticker_handlers.values():
        try:
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
    queue_handler = SimpleQueueHandler(log_queue)
    root = logging.getLogger()
    root.handlers = [queue_handler]
    root.setLevel(logging.DEBUG)

    # Suppress noisy per-cycle APScheduler INFO lines; only keep warnings and errors
    logging.getLogger('apscheduler').setLevel(logging.WARNING)

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
        log_queue.put(None)
    except Exception:
        pass

    log_proc.join(timeout)
    if log_proc.is_alive():
        try:
            log_proc.terminate()
        except Exception:
            pass
        log_proc.join(1.0)

def subprocess_init(log_queue: mp.SimpleQueue) -> None:
    h = SimpleQueueHandler(log_queue)
    logger = logging.getLogger()
    logger.handlers = [h]  # Replace all handlers with the queue handler
    logger.setLevel(logging.DEBUG)

# ── JSONL event ledger ────────────────────────────────────────────────────────

_ledger = logging.getLogger("ledger")
_seq = 0

def log_event(event_type: str, **fields):
    """
    Emit a structured JSON event to events.jsonl via the ledger logger.
    Thread- and process-safe: records flow through the shared SimpleQueue
    to the single logging process, which serialises writes to disk.
    """
    global _seq
    _seq += 1
    record = {
        "seq":   _seq,
        "ts":    _datetime.now().isoformat(timespec="seconds"),
        "event": event_type,
        **fields,
    }
    _ledger.info(json.dumps(record, default=str))

# ====== Example usage ====== TODO: this needs to be rewritten to accommodate new implementation ======
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
    log_config = log_init("test_log.log")
    log_queue, log_proc = start_logging_process(log_config)
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
    stop_logging_process(log_queue, log_proc)
