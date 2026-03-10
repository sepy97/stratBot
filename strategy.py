import util
from BackTestStrategy import BackTestStrategy


class Strategy(BackTestStrategy):
    """
    Live-trading strategy wrapper.  Extends BackTestStrategy with helpers that
    are only meaningful during live trading (e.g. intraday stop management).
    """

    def tighten_entry_stop(self, chart, trade_data):
        """
        Recalculates the stop using the current chart and returns the tighter
        of the new value vs the existing stop — the stop can only move closer
        to entry, never further away.

        Some getStop implementations write trade_data['stop'] as a side effect
        before returning; we save and restore to keep the comparison clean.
        """
        existing_stop = trade_data['stop']
        result = self.getStop(chart, None, trade_data)
        new_stop = result[0]
        # Restore in case getStop mutated trade_data['stop'] as a side effect
        trade_data['stop'] = existing_stop
        if trade_data['direction'] == util.TickerStatus.LONG:
            tighter = max(existing_stop, new_stop)
        else:
            tighter = min(existing_stop, new_stop)
        # Return full result tuple with the tightened stop so callers can also
        # update exit_comment and target from the same getStop call.
        return (tighter,) + result[1:]
