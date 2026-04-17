import json
import logging
import os
import queue
import signal
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data import StockHistoricalDataClient
from apscheduler.schedulers.background import BackgroundScheduler

import log_functions
import MarketTimeManager as mtm
import util
from alpaca_config import alpaca_config
from BackTester import printTradeDict
from Broker import Broker
from DataRetrieval import DataRetrieval
from strategy import Strategy
from Ticker import Ticker

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger(log_functions.CHANNEL_TRADES)
system_logger = logging.getLogger(log_functions.CHANNEL_SYSTEM)
market_logger = logging.getLogger(log_functions.CHANNEL_MARKET)


def scheduling(
    symbols, DR_queue, DR_condition, TF, TF_condition, market_time_manager,
    tickers=None, time_quant=5,
):
    current_time = datetime.now()
    DR_queue.put(symbols)
    with DR_condition:
        DR_condition.notify()
    # print("Data retrieval signal sent", flush=True)
    for t in TF:
        TF[t] = False
        if candle_flipped := market_time_manager.detectTFFlip(
            current_time, mtm.timeframe_LUT[t][0], time_quant
        ):
            TF[t] = True
            market_logger.info(f"TF {t} flipped @ {current_time}")
    with TF_condition:
        TF_condition.notify_all()
    # print("Timeframe signal sent to all tickers", flush=True)
    if tickers is not None:
        _write_status(tickers, market_time_manager)
    return


_bot_start_time = time.time()
_last_status_write_error_time = 0.0


def _write_status(tickers, market_time_manager):
    """Write live status to ~/.stratbot/status.json every scheduler tick."""
    global _last_status_write_error_time
    try:
        paused = util.PAUSE_FLAG.exists()
        now_ts = int(time.time())
        open_positions = []
        for t in tickers:
            for tr in t.active_trades:
                open_positions.append({
                    "symbol": tr.data["symbol"],
                    "direction": tr.direction.name,
                    "entry": tr.data["entryPrice"],
                    "days_open": tr.data["daysOpen"],
                    "strategy": tr.strategy.name,
                })
        market_day = market_time_manager.getOpenCloseAtDay(now_ts)
        market_day_open = market_day.get("open", 0) if isinstance(market_day, dict) else 0
        market_day_close = market_day.get("close", 0) if isinstance(market_day, dict) else 0
        has_valid_market_day_window = market_day_close > market_day_open
        trades_closed_today = 0
        if has_valid_market_day_window:
            for t in tickers:
                for tr in t.trade_history:
                    exit_ts = tr.data.get("exitTimestamp_sec")
                    if exit_ts is not None and market_day_open <= exit_ts < market_day_close:
                        trades_closed_today += 1

        status = {
            "pid": os.getpid(),
            "state": "paused" if paused else "running",
            "paused": paused,
            "timestamp": now_ts,
            "uptime_seconds": int(now_ts - _bot_start_time),
            "market_open": market_time_manager.isMarketOpen(now_ts),
            "tickers_active": len(tickers),
            "trades_open": len(open_positions),
            "trades_closed_today": trades_closed_today,
            "realized_pnl": round(
                sum(tr.realized_pnl() or 0 for t in tickers for tr in t.trade_history),
                2,
            ),
            "open_positions": open_positions,
        }
        util.STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(util.STATUS_FILE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(status, f, indent=2)
        os.replace(tmp, util.STATUS_FILE)
    except Exception as exc:
        # Status write is best-effort, never crash the scheduler.
        # Rate-limit logs to avoid flooding if a persistent issue occurs.
        now = time.time()
        if now - _last_status_write_error_time >= 60:
            _last_status_write_error_time = now
            system_logger.warning(f"Failed to write status file: {exc}", exc_info=True)


def log_session_summary(tickers):
    """Log performance statistics for all closed trades in the session."""
    all_closed = [trade for t in tickers for trade in t.trade_history]
    if not all_closed:
        trades_logger.info("Session summary: no closed trades.")
        return

    total = len(all_closed)
    pnl_values = [tr.realized_pnl() for tr in all_closed]
    start_values = [tr.starting_value() for tr in all_closed]
    wins = sum(1 for pnl in pnl_values if pnl is not None and pnl > 0)
    total_pnl = sum(pnl for pnl in pnl_values if pnl is not None)
    total_start = sum(start_values)
    total_gain_pct = 100 * total_pnl / total_start if total_start else 0

    by_strategy = {}
    for tr in all_closed:
        name = tr.strategy.name
        by_strategy.setdefault(name, []).append(tr)

    lines = [
        "========================",
        f"  Session summary:",
        f"  Total trades : {total}",
        f"  Win rate     : {100 * wins / total:.1f}%  ({wins}/{total})",
        f"  Total PnL    : ${total_pnl:.2f}",
        f"  Total gain   : {total_gain_pct:.2f}%",
    ]
    for strat_name, trades in by_strategy.items():
        s_total = len(trades)
        s_pnl_values = [tr.realized_pnl() for tr in trades]
        s_start_values = [tr.starting_value() for tr in trades]
        s_wins = sum(1 for pnl in s_pnl_values if pnl is not None and pnl > 0)
        s_pnl = sum(pnl for pnl in s_pnl_values if pnl is not None)
        s_start = sum(s_start_values)
        s_gain_pct = 100 * s_pnl / s_start if s_start else 0
        lines.append(
            f"  [{strat_name}] trades={s_total}, "
            f"wins={s_wins} ({100 * s_wins / s_total:.1f}%), "
            f"pnl=${s_pnl:.2f}, gain={s_gain_pct:.2f}%"
        )
    lines.append("========================")
    summary = "\n".join(lines)
    trades_logger.info(summary)


def _get_next_market_open(market_time_manager):
    """Return the next market open timestamp (seconds), or None on failure.

    Scans up to 10 days forward using getOpenCloseAtDay() to find the
    next trading day.
    """
    now_ts = int(time.time())
    for day_offset in range(1, 11):
        future_ts = now_ts + day_offset * 86400
        schedule = market_time_manager.getOpenCloseAtDay(future_ts)
        if schedule['open'] > 0:
            return schedule['open']
    return None


def _refresh_candles(tickers, data_retriever):
    """Re-fetch candle windows for all tickers after overnight sleep."""
    for t in tickers:
        try:
            data = data_retriever.get_initial_data(
                t.symbol, ["m5", "m15", "m30", "m60", "d", "w", "m", "q"]
            )
            if data:
                t.initializeCandles(data)
                logger.debug(f"{t.symbol}: candles refreshed")
            else:
                logger.warning(f"{t.symbol}: failed to refresh candles")
        except Exception as e:
            logger.warning(f"{t.symbol}: error refreshing candles: {e}")


# ── State persistence ────────────────────────────────────────────────────────


def _save_session(tickers):
    """Save active trades to JSON for resume on next startup.

    Uses atomic write (temp file → os.replace) to prevent corruption.
    """
    state = {
        "version": 1,
        "saved_at": int(time.time()),
        "tickers": {},
    }
    for t in tickers:
        if t.active_trades:
            state["tickers"][t.symbol] = {
                "active_trades": [
                    {
                        **tr.data,
                        "strategy_name": tr.strategy.name,
                        "direction": tr.direction.name,
                    }
                    for tr in t.active_trades
                ]
            }
    util.SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(util.SESSION_STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, util.SESSION_STATE_FILE)
    system_logger.info(
        f"Session state saved: {sum(len(v['active_trades']) for v in state['tickers'].values())} trade(s)"
    )


def _load_session():
    """Load saved session state, or return None if no state file exists."""
    if not util.SESSION_STATE_FILE.exists():
        return None
    try:
        with open(util.SESSION_STATE_FILE) as f:
            state = json.load(f)
        age_hours = (time.time() - state.get("saved_at", 0)) / 3600
        if age_hours > 24:
            system_logger.warning(
                f"Session state is {age_hours:.1f}h old — consider --fresh"
            )
        return state
    except (json.JSONDecodeError, KeyError) as e:
        system_logger.warning(f"Corrupt session state, ignoring: {e}")
        return None


# ── Signal-based shutdown ─────────────────────────────────────────────────────

_shutdown_event = threading.Event()
_force_close = False  # True when SIGUSR1 (kill-switch) is received


def _handle_graceful(signum, frame):
    """SIGTERM / SIGINT → graceful exit: save state, keep positions open."""
    system_logger.info(f"Received signal {signum} — graceful shutdown")
    _shutdown_event.set()


def _handle_terminate(signum, frame):
    """SIGUSR1 → kill-switch: force-close all positions, delete state."""
    global _force_close
    system_logger.info(f"Received signal {signum} — force-close shutdown")
    _force_close = True
    _shutdown_event.set()


# entry point for the program
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="stratBot live trading")
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ignore saved session state, start clean",
    )
    parser.add_argument(
        "--terminate", action="store_true",
        help="Force-close all saved positions and exit immediately",
    )
    cli_args = parser.parse_args()

    # Handle --terminate: close saved positions without starting the bot
    if cli_args.terminate:
        saved = _load_session()
        if saved and saved.get("tickers"):
            symbols = [s for s, v in saved["tickers"].items() if v.get("active_trades")]
            print(f"Terminate: {len(symbols)} symbol(s) with open trades: {symbols}")
            print("TODO: broker force-close not yet wired — delete state file only")
        util.SESSION_STATE_FILE.unlink(missing_ok=True)
        print("Session state deleted.")
        raise SystemExit(0)

    # INITIALIZATION

    # Register signal handlers before anything else
    signal.signal(signal.SIGTERM, _handle_graceful)
    signal.signal(signal.SIGINT, _handle_graceful)
    signal.signal(signal.SIGUSR1, _handle_terminate)

    # Write PID file
    util.STRATBOT_DIR.mkdir(parents=True, exist_ok=True)
    util.PID_FILE.write_text(str(os.getpid()))

    # Set up unified logging, writing directly to the shared iCloud directory.
    # Archive any stale logs from a previous crashed session BEFORE
    # starting the new logging process (Option C: mode='a' + fresh dir).
    log_dir = os.path.join(util.getLogPath(), util.getUsername(), "current")
    os.makedirs(log_dir, exist_ok=True)
    try:
        util.moveLogs(log_dir=log_dir)
    except (FileNotFoundError, OSError):
        pass  # First run or already clean — nothing to archive
    os.makedirs(log_dir, exist_ok=True)
    log_queue, log_proc = log_functions.start_logging_process(
        log_functions.log_init("live_trading.log", log_dir=log_dir)
    )
    log_functions.log_event("session_start", mode="live")

    # Route uncaught thread exceptions through the logging system instead of stderr
    def _thread_excepthook(args):
        logger.error(
            "Uncaught exception in thread '%s'",
            args.thread.name if args.thread else "<unknown>",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

    try:
        # load watchlist from csv (same file used by backtester)
        watchlist = pd.read_csv("Watchlists/NASDAQ100_2025.csv", header=None)[
            0
        ].to_list()
        session = StockHistoricalDataClient(
            alpaca_config["key"], alpaca_config["secret_key"]
        )
        market_time_manager = mtm.MarketTimeManager()

        # create global queues for scheduled data retrieval, for data with tickers quotes, and for signals to broker
        # each queue is used for communication between different threads
        # in the DR_queue each element is the current "watchlist"
        DR_queue = queue.Queue()
        DR_condition = threading.Condition()
        # there are multiple ticker queues, one queue for each ticker in the watchlist
        ticker_queues = {symbol: queue.Queue() for symbol in watchlist}
        ticker_condition = threading.Condition()
        # broker queue contains symbols that should be traded
        broker_queue = queue.Queue()
        broker_condition = threading.Condition()
        # TF is a dictionary of timeframes and boolean values that indicate if the timeframe is flipped; initialized by True for all timeframes
        TF = {
            "m5": True,
            "m15": True,
            "m30": True,
            "m60": True,
            "d": True,
            "w": True,
            "m": True,
            "q": True,
        }
        TF_condition = threading.Condition()
        time_quant = (
            5  # interval (in seconds) before the next data retrieval and trigger checks
        )

        # authorize data retriever
        data_retriever = DataRetrieval(
            session,
            watchlist,
            DR_queue,
            ticker_queues,
            DR_condition,
            ticker_condition,
            daemon=True,
        )
        # data_retriever should send data (via map) to ticker threads
        data_retriever.start()

        # authorize broker
        broker = Broker(broker_queue, broker_condition, daemon=True)
        # broker should wait for signals from ticker threads
        broker.start()

        # get tickers from watchlist, create an iterable collection of threads, and start threads for each ticker
        tickers = []
        valid_watchlist = []
        for symbol in watchlist:
            data = data_retriever.get_initial_data(
                symbol, ["m5", "m15", "m30", "m60", "d", "w", "m", "q"]
            )
            if data is None:
                continue
            t = Ticker(
                symbol,
                ticker_queues[symbol],
                TF,
                broker_queue,
                ticker_condition,
                TF_condition,
                broker_condition,
                daemon=True,
            )
            t.strategies.append(Strategy("BasicDailyAS"))
            t.strategies.append(Strategy("StratLab2dGM"))
            t.initializeCandles(data)
            tickers.append(t)
            valid_watchlist.append(symbol)
        system_logger.info(
            f"Initialized {len(valid_watchlist)}/{len(watchlist)} symbols successfully."
        )

        # ── Resume from saved state ──────────────────────────────────
        if not cli_args.fresh:
            saved = _load_session()
            if saved and saved.get("tickers"):
                from Trade import Trade

                resumed_count = 0
                for t in tickers:
                    saved_ticker = saved["tickers"].get(t.symbol)
                    if not saved_ticker or not saved_ticker.get("active_trades"):
                        continue
                    for trade_dict in saved_ticker["active_trades"]:
                        strat_name = trade_dict.pop("strategy_name", None)
                        strategy_obj = next(
                            (s for s in t.strategies if s.name == strat_name), None
                        )
                        if strategy_obj is None:
                            logger.warning(
                                f"{t.symbol}: unknown strategy '{strat_name}' "
                                f"in saved state, skipping trade"
                            )
                            continue
                        try:
                            trade = Trade.from_dict(trade_dict, strategy_obj)
                        except ValueError as exc:
                            logger.warning(
                                f"{t.symbol}: {exc}, skipping trade from saved state"
                            )
                            continue
                        t.active_trades.append(trade)
                        resumed_count += 1
                if resumed_count:
                    system_logger.info(
                        f"Resumed {resumed_count} open trade(s) from saved state"
                    )
        for t in tickers:
            # each thread should first initialize the ticker, then start waiting for the signal from the data retriever
            t.start()

        # create global APScheduler and schedule data retrieval (by function that adds signal to the queue) every 5 seconds
        scheduler = BackgroundScheduler()
        proper_start_time = market_time_manager.getProperStartTime(
            datetime.now(), time_quant
        )
        system_logger.info(f"Proper start time: {proper_start_time}")
        system_logger.info(
            f"Opening time: {datetime.fromtimestamp(market_time_manager.getTodayOpenTime())}"
        )
        scheduler.add_job(
            lambda: scheduling(
                valid_watchlist,
                DR_queue,
                DR_condition,
                TF,
                TF_condition,
                market_time_manager,
                tickers=tickers,
                time_quant=time_quant,
            ),
            "interval",
            seconds=5,
            timezone="America/Los_Angeles",
            start_date=proper_start_time,
        )
        scheduler.add_job(
            lambda: _save_session(tickers),
            "interval",
            minutes=5,
            id="periodic_state_save",
        )
        scheduler.start()

        # ── Market-aware main loop ────────────────────────────────────
        # Runs continuously: trades during market hours, sleeps overnight.
        # Exits when _shutdown_event is set (via SIGTERM, SIGINT, or SIGUSR1).
        system_logger.info("Entering market-aware main loop")
        while not _shutdown_event.is_set():
            now_ts = int(time.time())
            if market_time_manager.isMarketOpen(now_ts):
                _shutdown_event.wait(timeout=1)
            else:
                next_open = _get_next_market_open(market_time_manager)
                if next_open is None:
                    system_logger.warning(
                        "Could not determine next market open; retrying in 60s"
                    )
                    _shutdown_event.wait(timeout=60)
                    continue
                sleep_sec = max(1, next_open - now_ts - 20 * 60)
                system_logger.info(
                    f"Market closed. Sleeping {sleep_sec // 3600}h "
                    f"{(sleep_sec % 3600) // 60}m until pre-market."
                )
                _shutdown_event.wait(timeout=sleep_sec)
                if _shutdown_event.is_set():
                    break
                system_logger.info("Waking up — refreshing candle data")
                _refresh_candles(tickers, data_retriever)

        # ── Shutdown sequence ─────────────────────────────────────────
        # Stop the scheduler first so no new ticks can fire during shutdown.
        scheduler.shutdown(wait=True)

        # Stop data and ticker threads
        data_retriever.stopThr()
        for t in tickers:
            t.stopThr()

        if _force_close:
            # ── TERMINATE (kill-switch): force-close all positions ────
            system_logger.info("Kill-switch: force-closing all positions")
            now = time.time()
            for t in tickers:
                if not t.active_trades:
                    continue
                last_price = None
                for tf in ("m5", "m15", "d"):
                    if t.candles.get(tf):
                        last_price = t.candles[tf][0].close
                        break
                if last_price is None:
                    logger.warning(
                        f"Cannot force-close {t.symbol}: no candle data, "
                        f"{len(t.active_trades)} trade(s) left open"
                    )
                    continue
                for trade in list(t.active_trades):
                    trade.force_close(last_price, now)
                    t.trade_history.append(trade)
                    t.active_trades.remove(trade)
                    broker_queue.put(
                        {
                            "action": "EXIT",
                            "symbol": t.symbol,
                            "price": trade.data["exitPrice"],
                            "direction": trade.direction,
                        }
                    )
                    with broker_condition:
                        broker_condition.notify()
                    log_functions.log_event(
                        "forced_close",
                        symbol=t.symbol,
                        strategy=trade.strategy.name,
                        direction=trade.direction.name,
                        price=last_price,
                        gain_pct=round(trade.data["gain %"], 4),
                    )
                    trades_logger.info(
                        f"EXIT {t.symbol}: forced close @ {last_price:.2f}, "
                        f"gain={trade.data['gain %']:.2f}%, "
                        f"strategy={trade.strategy.name}"
                    )
        else:
            # ── GRACEFUL EXIT: positions stay open at broker ──────────
            _save_session(tickers)
            open_count = sum(len(t.active_trades) for t in tickers)
            system_logger.info(
                f"Graceful exit: {open_count} position(s) left open at broker"
            )

        broker.stopThr()
        log_session_summary(tickers)

        # Export all trades (completed + still-open) to CSV
        all_trades = {
            t.symbol: [trade.data for trade in t.trade_history + t.active_trades]
            for t in tickers
        }
        if any(all_trades.values()):
            os.makedirs("Trades", exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            printTradeDict(all_trades, f"Trades/live_trades_{ts}.csv")

        if _force_close:
            # Delete state so next start is fresh
            try:
                util.SESSION_STATE_FILE.unlink(missing_ok=True)
            except Exception:
                pass

        log_functions.log_event(
            "session_end",
            mode="terminate" if _force_close else "graceful",
        )
        util.moveLogs(log_dir=log_dir)
    except Exception:
        logger.exception("Fatal error in main process")
        raise
    finally:
        # Clean up PID and status files
        try:
            util.PID_FILE.unlink(missing_ok=True)
            util.STATUS_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        log_functions.stop_logging_process(log_queue, log_proc)
