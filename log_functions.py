import json
import logging
import logging.handlers
import multiprocessing as mp
import os
import sys
from datetime import datetime as _datetime
from time import sleep

# ── Logger channel constants ─────────────────────────────────────────────────
# Import these instead of hardcoding logger names:
#   from log_functions import CHANNEL_TRADES
#   trades_logger = logging.getLogger(CHANNEL_TRADES)

CHANNEL_TRADES = "trades"
CHANNEL_SYSTEM = "system"
CHANNEL_MARKET = "market"
CHANNEL_BROKER = "broker"
CHANNEL_LEDGER = "ledger"


class SimpleQueueHandler(logging.Handler):
    """A QueueHandler that works with mp.SimpleQueue.

    Materialises the log message and converts exc_info to a string
    *before* putting the record on the queue so that the resulting
    LogRecord is safe to pickle across process boundaries.
    """
    def __init__(self, queue: mp.SimpleQueue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        try:
            record.msg = record.getMessage()
            record.args = None
            # Format traceback into a string so the record is picklable
            if record.exc_info:
                record.exc_text = self.format(record) if not record.exc_text else record.exc_text
                record.exc_info = None
            self.queue.put(record)
        except Exception:
            self.handleError(record)


class MainLogFilter(logging.Filter):
    """Filters records for the console and app.log handlers.

    - trades:  show all (DEBUG+)  — every trade event is important
    - system/broker/market: INFO+ — suppress DEBUG chatter
    - Ticker.*: INFO+             — suppress per-bar debug noise
    - ledger:  suppress entirely  — JSON goes only to events.jsonl
    - default: INFO+
    """
    RULES = {
        CHANNEL_TRADES: logging.DEBUG,
        CHANNEL_SYSTEM: logging.INFO,
        CHANNEL_BROKER: logging.INFO,
        CHANNEL_MARKET: logging.INFO,
        CHANNEL_LEDGER: None,           # suppress (routed separately)
    }

    def filter(self, record):
        if record.name in self.RULES:
            threshold = self.RULES[record.name]
            return threshold is not None and record.levelno >= threshold
        if record.name.startswith("Ticker."):
            return record.levelno >= logging.INFO
        return record.levelno >= logging.INFO


def _make_handler(path, formatter, level=logging.DEBUG, mode='a'):
    """Create a FileHandler with the given settings.

    Fails fast if the file cannot be opened — better to crash at
    startup than silently lose logs.  Permission is set to 0o600
    (owner-only) for security.
    """
    h = logging.FileHandler(path, mode=mode)
    h.setFormatter(formatter)
    h.setLevel(level)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return h


def _inject_seq(record, seq):
    """Parse a ledger LogRecord's JSON message, inject *seq*, and
    return a new LogRecord with the updated payload.  Falls back to
    the original record if the JSON is malformed."""
    try:
        d = json.loads(record.getMessage())
        d["seq"] = seq
        return logging.LogRecord(
            name="ledger", level=logging.INFO,
            pathname="", lineno=0,
            msg=json.dumps(d, default=str),
            args=(), exc_info=None,
        )
    except (json.JSONDecodeError, TypeError):
        return record


def log_init(log_file="strat_bot.log", trades_file="trades.log",
             log_dir=".", symbols=None):
    """Return a picklable config dict consumed by the logging process.

    Args:
        log_file:    main log filename
        trades_file: trades-only log filename
        log_dir:     directory to write all logs (default ".")
        symbols:     list of ticker symbols (e.g. ["AAPL", "MSFT"]) for
                     pre-creating per-ticker handlers.  If None, ticker
                     handlers are created on-demand.
    """
    return {
        "log_file":      os.path.join(log_dir, log_file),
        "trades_file":   os.path.join(log_dir, trades_file),
        "ledger_file":   os.path.join(log_dir, "events.jsonl"),
        "log_dir":       log_dir,
        "symbols":       symbols or [],
        "console_level": logging.INFO,
        "file_level":    logging.DEBUG,
        "fmt":     "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }


def _logging_process_main(log_queue: mp.SimpleQueue, config: dict):
    """Dedicated logging process — receives LogRecords from all workers
    and the main process and writes them to the appropriate files.

    Data sensitivity policy:
    - app.log:              Full operational log (sensitive)
    - trades.log:           Trade events only (sensitive)
    - events.jsonl:         Structured audit trail (sensitive, seq'd)
    - tickers/strat_*.log:  Market data + signals (moderate)
    - console:              Filtered operator view
    """
    formatter = logging.Formatter(config["fmt"], config["datefmt"])
    ledger_formatter = logging.Formatter("%(message)s")
    log_filter = MainLogFilter()

    # ── Root handlers (console + app.log) ────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(config["console_level"])
    console_handler.setFormatter(formatter)
    console_handler.addFilter(log_filter)

    file_handler = _make_handler(config["log_file"], formatter,
                                 level=config["file_level"])
    file_handler.addFilter(log_filter)

    root = logging.getLogger()
    root.handlers = [console_handler, file_handler]
    root.setLevel(logging.DEBUG)

    # ── Domain-specific route handlers ───────────────────────────────
    trades_handler = _make_handler(config["trades_file"], formatter)
    ledger_handler = _make_handler(config["ledger_file"], ledger_formatter)

    routes = {
        CHANNEL_TRADES: trades_handler,
    }

    # ── Pre-create per-ticker handlers ───────────────────────────────
    ticker_handlers: dict = {}
    tickers_dir = os.path.join(config["log_dir"], "tickers")
    if config["symbols"]:
        os.makedirs(tickers_dir, exist_ok=True)
        for sym in config["symbols"]:
            ticker_handlers[sym] = _make_handler(
                os.path.join(tickers_dir, f"strat_{sym}.log"), formatter)

    # ── Ledger sequence counter (single-writer, monotonic) ───────────
    ledger_seq = 0
    record_count = 0

    while True:
        try:
            record = log_queue.get()
        except (EOFError, OSError):
            break
        if record is None:
            break

        record_count += 1

        try:
            # ── Ledger: inject seq, route ONLY to events.jsonl ───────
            if record.name == CHANNEL_LEDGER:
                ledger_seq += 1
                record = _inject_seq(record, ledger_seq)
                if ledger_handler:
                    ledger_handler.emit(record)
                # Periodic monitoring
                if record_count % 5000 == 0:
                    _check_health(log_queue, config, root)
                continue  # skip root.handle() — no JSON in app.log

            # ── Everything else → console + app.log via root ─────────
            root.handle(record)

            # ── Route to domain-specific file if applicable ──────────
            if record.name in routes and routes[record.name] is not None:
                routes[record.name].emit(record)

            # ── Route Ticker.<symbol> to per-ticker files ────────────
            elif record.name.startswith("Ticker."):
                sym = record.name.split(".", 1)[1]
                if sym not in ticker_handlers:
                    os.makedirs(tickers_dir, exist_ok=True)
                    ticker_handlers[sym] = _make_handler(
                        os.path.join(tickers_dir, f"strat_{sym}.log"),
                        formatter)
                ticker_handlers[sym].emit(record)

        except Exception:
            import traceback
            traceback.print_exc()

        # Periodic health monitoring
        if record_count % 5000 == 0:
            _check_health(log_queue, config, root)

    # ── Clean exit ───────────────────────────────────────────────────
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    for h in [trades_handler, ledger_handler]:
        try:
            h.close()
        except Exception:
            pass
    for h in ticker_handlers.values():
        try:
            h.close()
        except Exception:
            pass


def _check_health(log_queue, config, root):
    """Periodic queue-depth and file-size checks."""
    try:
        if hasattr(log_queue, 'qsize'):
            depth = log_queue.qsize()
            if depth > 500:
                root.warning(f"Log queue depth: {depth} — logging may be falling behind")
    except Exception:
        pass
    try:
        size = os.path.getsize(config["log_file"])
        if size > 500_000_000:  # 500 MB
            root.warning(
                f"Main log file is {size / 1e9:.1f} GB — consider archiving")
    except OSError:
        pass


def start_logging_process(config):
    """Create log_queue and start the logging process.

    Also configures the main process root logger to send all logs
    to the queue.
    """
    log_queue = mp.SimpleQueue()

    queue_handler = SimpleQueueHandler(log_queue)
    root = logging.getLogger()
    root.handlers = [queue_handler]
    root.setLevel(logging.DEBUG)

    # Suppress noisy per-cycle APScheduler INFO lines
    logging.getLogger('apscheduler').setLevel(logging.WARNING)

    log_proc = mp.Process(
        target=_logging_process_main,
        args=(log_queue, config),
        daemon=True,
    )
    log_proc.start()

    return log_queue, log_proc


def stop_logging_process(log_queue: mp.SimpleQueue, log_proc: mp.Process,
                         timeout: float = 5.0):
    """Stop the logging process by sending sentinel and joining it.

    If it doesn't exit within *timeout* seconds, terminate it.
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
    """Configure a worker subprocess to send logs through the shared queue."""
    h = SimpleQueueHandler(log_queue)
    logger = logging.getLogger()
    logger.handlers = [h]
    logger.setLevel(logging.DEBUG)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)


# ── JSONL event ledger ────────────────────────────────────────────────────────

_ledger = logging.getLogger(CHANNEL_LEDGER)

def log_event(event_type: str, **fields):
    """Emit a structured JSON event to events.jsonl via the ledger logger.

    The ``seq`` field is injected by the logging process (single writer)
    to guarantee monotonic ordering across all threads and processes.

    WARNING: Do NOT log API keys, tokens, or PII in *fields*.
    """
    record = {
        "ts":    _datetime.now().isoformat(timespec="seconds"),
        "event": event_type,
        **fields,
    }
    _ledger.info(json.dumps(record, default=str))
