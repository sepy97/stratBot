import util
import time as _time


class Trade:
    """
    Represents a single live trade. Mirrors the backtester trade dictionary.
    One Ticker may have multiple Trade objects active at once.

    self.data holds the same fields used by the backtester trade dict so that
    BackTestStrategy.getStop() and related functions work unchanged.
    """

    def __init__(self, symbol, triggerPrice, direction, chart, strategy, quantity=1):
        self.strategy = strategy   # not in self.data so CSV export is unaffected
        tgt = float('inf') if direction == util.TickerStatus.LONG else 0.0
        self.data = {
            'symbol': symbol,
            'quantity': quantity,
            'entryPrice': triggerPrice,
            'entryTimestamp_sec': int(_time.time()),
            'daysOpen': 0,
            'direction': direction,
            'exitPrice': -1,
            'exitTimestamp_sec': -1,
            'gain %': -1,
            'stop type': '',
            'target': tgt,
            'exit_comment': '',
        }
        self._record_combos(chart, triggerPrice, direction)
        self._init_stop(chart, strategy)

    # ── deserialization ────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data_dict, strategy):
        """Reconstruct a Trade from a saved state dict.

        Used on resume to re-populate Ticker.active_trades from
        session_state.json.  Bypasses __init__ since we already have
        the fully-populated data dict and don't need chart context.
        """
        trade = cls.__new__(cls)
        trade.data = data_dict.copy()
        trade.strategy = strategy
        # Convert direction string back to enum if it was serialised
        if isinstance(trade.data.get('direction'), str):
            try:
                trade.data['direction'] = util.TickerStatus[trade.data['direction']]
            except KeyError as exc:
                raise ValueError(
                    f"invalid trade direction '{trade.data['direction']}' "
                    f"for symbol '{trade.data.get('symbol', 'UNKNOWN')}'"
                ) from exc
        return trade

    # ── active trade management ───────────────────────────────────────────────

    def tighten_entry_stop(self, chart):
        """
        Delegate to the strategy's tighten_entry_stop and apply the result.
        Also updates exit_comment and target when the strategy returns them.
        """
        result = self.strategy.tighten_entry_stop(chart, self.data)
        self.data['stop'] = result[0]
        self.data['exit_comment'] = result[1]
        if len(result) > 2:
            self.data['target'] = result[2]

    def check_exit(self, bar_high, bar_low, timestamp):
        """
        Check bar high/low against stop and target.
        Returns True if the trade was closed, False otherwise.
        Updates self.data in place on exit.
        """
        d = self.data
        exited = False
        if d['direction'] == util.TickerStatus.LONG:
            if bar_low <= d['stop']:
                d['stop type'] = "stop hit"
                d['exitPrice'] = d['stop']
                exited = True
            elif bar_high >= d['target']:
                d['stop type'] = "target hit"
                d['exitPrice'] = d['target']
                exited = True
        else:
            if bar_high >= d['stop']:
                d['stop type'] = "stop hit"
                d['exitPrice'] = d['stop']
                exited = True
            elif bar_low <= d['target']:
                d['stop type'] = "target hit"
                d['exitPrice'] = d['target']
                exited = True
        if exited:
            d['exitTimestamp_sec'] = int(timestamp)
            d['gain %'] = self._calc_gain()
        return exited

    def force_close(self, price, timestamp):
        """Force-close the trade at the given price (e.g. at shutdown)."""
        d = self.data
        d['exitPrice'] = price
        d['exitTimestamp_sec'] = int(timestamp)
        d['stop type'] = 'forced close'
        d['gain %'] = self._calc_gain()

    def realized_pnl(self):
        """Return closed-trade P&L in dollars, or None while trade is open."""
        ep = self.data['exitPrice']
        if ep == -1:
            return None
        qty = self.data.get('quantity', 1)
        entry = self.data['entryPrice']
        if self.data['direction'] == util.TickerStatus.LONG:
            return (ep - entry) * qty
        return (entry - ep) * qty

    def starting_value(self):
        """Notional capital allocated at entry for this trade."""
        return self.data['entryPrice'] * self.data.get('quantity', 1)

    def ending_value(self):
        """Capital after close for this trade, or None while trade is open."""
        pnl = self.realized_pnl()
        if pnl is None:
            return None
        return self.starting_value() + pnl

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def is_open(self):
        return self.data['exitPrice'] == -1

    @property
    def stop(self):
        return self.data['stop']

    @property
    def direction(self):
        return self.data['direction']

    # ── private helpers ───────────────────────────────────────────────────────

    def _init_stop(self, chart, strategy):
        """Get initial stop from strategy and compute RR. chartDictOld is None
        because at entry time we don't have a separate old-chart snapshot; the
        strategies used here (BasicDailyAS etc.) don't read chartDictOld for
        the initial stop anyway."""
        result = strategy.getStop(chart, None, self.data)
        self.data['stop'] = result[0]
        self.data['initial stop'] = result[0]
        self.data['initialStop'] = result[0]
        self.data['exit_comment'] = result[1]
        if len(result) > 2:
            self.data['target'] = result[2]
        denom = self.data['entryPrice'] - self.data['stop']
        self.data['RR'] = (
            (self.data['target'] - self.data['entryPrice']) / denom
            if denom != 0 else float('inf')
        )

    def _record_combos(self, chart, triggerPrice, direction):
        """
        Record candle combo strings and TFC for all timeframes present in chart.
        Mirrors the combo-recording block in BackTester.enterTrade().
        Uses the live (partially-formed) candle at index [-1] as the entry candle.
        """
        adj = 0.01 if direction == util.TickerStatus.LONG else -0.01
        entry_adj = triggerPrice + adj
        for tf, cdls in chart.items():
            if len(cdls) >= 3:
                self.data[tf] = (
                    cdls[-3].to_string() + "-" +
                    cdls[-2].to_string() + "-" +
                    cdls[-1].to_string()
                )
                self.data[tf + " combo"] = (
                    cdls[-3].get_kind() + cdls[-3].get_subtype() + "-" +
                    cdls[-2].get_kind() + cdls[-2].get_subtype() + "-" +
                    cdls[-1].get_kind() + cdls[-1].get_subtype()
                )
            elif len(cdls) == 2:
                self.data[tf] = cdls[-2].to_string() + "-" + cdls[-1].to_string()
                self.data[tf + " combo"] = (
                    cdls[-2].get_kind() + cdls[-2].get_subtype() + "-" +
                    cdls[-1].get_kind() + cdls[-1].get_subtype()
                )
            if len(cdls) >= 1:
                self.data["TFC " + tf] = "G" if entry_adj > cdls[-1].open else "R"
        if 'd' in chart and len(chart['d']) >= 2:
            self.data["Prev D pattern"] = chart['d'][-2].get_pattern()

    def _calc_gain(self):
        ep = self.data['exitPrice']
        if ep == -1:
            return None
        if self.data['direction'] == util.TickerStatus.LONG:
            return 100 * (ep / self.data['entryPrice'] - 1)
        return 100 * (1 - ep / self.data['entryPrice'])
