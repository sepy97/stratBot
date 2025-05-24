import util
import pandas as pd
class BackTestStrategy:
    
    def __init__(self, name=""):
        self.name = name
        self.ignoreIfGap = True

    # This function returns the trigger price, stop price, and direction of the trade. If gaps are allowed - then the trigger price is the open price of the current candle
    def getNewTrade(self, chartDict, er_list):
        
        # SimpleDailyAS strategy: if AS on D in force + TFC on D, W, M (taken at trigger price)
        # Actionable signals: 1-2, 2-2 reversal (so 2u-2d or 2d-2u). Gap over/under trigger should be ignored
        if self.name == "SimpleDailyAS":
            validTrade = False
            isLastDayBeforeER = pd.to_datetime(chartDict['d'][-1].open_ts, unit='s', utc=True).date() in er_list
            exit_comment = ""
            if isLastDayBeforeER:
                exit_comment = f"Last day before ER - {pd.to_datetime(chartDict['d'][-1].open_ts, unit='s', utc=True).date()}| "
            stopPrice = 0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low)    # stop is 50% of trigger candle (will use only if actional signal is there)
            if (    # bullish
                # Previous candle is 1 or 2d (bullish)
                ((chartDict['d'][-2].get_kind() == "2" and chartDict['d'][-2].get_subtype() == "D") or chartDict['d'][-2].get_kind() == "1") and
                # Current candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDict['d'][-1].get_kind() == "2" and chartDict['d'][-1].get_subtype() == "U") or chartDict['d'][-1].get_kind() == "3") and
                # Check TFC - previous D high is the trigger price. Note that checking D continuity also ensures no gap over trigger
                (chartDict['d'][-1].open <= chartDict['d'][-2].high) and
                (chartDict['w'][-1].open <= chartDict['d'][-2].high) and
                (chartDict['m'][-1].open <= chartDict['d'][-2].high)
            ):
                validTrade = True
                triggerPrice = chartDict['d'][-2].high
                direction = util.TickerStatus.LONG
                if isLastDayBeforeER:
                    stopPrice = max(stopPrice, chartDict['d'][-1].close)
                #return chartDict['d'][-2].high, stopPrice, util.TickerStatus.LONG, entry_comment, exit_comment
            elif (  # bearish
                # Previous candle is 1 or 2u (bearish)
                ((chartDict['d'][-2].get_kind() == "2" and chartDict['d'][-2].get_subtype() == "U") or chartDict['d'][-2].get_kind() == "1") and
                # Current candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDict['d'][-1].get_kind() == "2" and chartDict['d'][-1].get_subtype() == "D") or chartDict['d'][-1].get_kind() == "3") and
                # Check TFC - previous D low is the trigger price. Note that checking D continuity also ensures no gap under trigger
                (chartDict['d'][-1].open >= chartDict['d'][-2].low) and
                (chartDict['w'][-1].open >= chartDict['d'][-2].low) and
                (chartDict['m'][-1].open >= chartDict['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDict['d'][-2].low
                direction = util.TickerStatus.SHORT
                if isLastDayBeforeER:
                    stopPrice = min(stopPrice, chartDict['d'][-1].close)
                #return chartDict['d'][-2].low, stopPrice, util.TickerStatus.SHORT, entry_comment, exit_comment
            
            if validTrade:
                # Build list of candle combos at each timeframe
                entry_comment = ("D: " + chartDict['d'][-2].to_string() + "-" + chartDict['d'][-1].to_string() + 
                    " W: " + chartDict['w'][-1].to_string() + "-" + chartDict['w'][-2].to_string() + 
                    " M: " + chartDict['m'][-1].to_string() + "-" + chartDict['m'][-2].to_string() + 
                    " Q: " + chartDict['q'][-1].to_string() + "-" + chartDict['q'][-2].to_string() +
                    " Y: " + chartDict['y'][-1].to_string() + "-" + chartDict['y'][-2].to_string() +"||")
                # Determine TFC
                for tf in ['d', 'w', 'm', 'q', 'y']:
                    if triggerPrice > chartDict[tf][-1].open:
                        entry_comment += "G|"
                    else:
                        entry_comment += "R|"
                return triggerPrice, stopPrice, direction, entry_comment, exit_comment
            else:
                return None, None, None, None, None
        else:
            raise ValueError(f"Strategy {self.name} not implemented in BackTestStrategy")
            
            
    def getStop(self, chartDict, trade, er_list):
        isLastDayBeforeER = pd.to_datetime(chartDict['d'][-1].open_ts, unit='s', utc=True).date() in er_list
        exitComment = ""
        if isLastDayBeforeER:
            exitComment = f"Last day before ER - {pd.to_datetime(chartDict['d'][-1].open_ts, unit='s', utc=True).date()}| "
        if self.name == "SimpleDailyAS":
            # SimpleDailyAS strategy: 
            # If trade is open at the same day stop is 50% of trigger (previous) candle --> not covered by this function since we assume we are not stopped out at least at the day of entry
            # If trade is open in the previous day - stop is breakeven
            # If trade is open before previous day - stop is at low (long) or high (short) of previous candle
            if trade['daysOpen'] == 0:
                if isLastDayBeforeER:
                    if trade['direction'] == util.TickerStatus.LONG:
                        return max(0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low), chartDict['d'][-1].close), exitComment
                    else:
                        return min(0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low), chartDict['d'][-1].close), exitComment
                else:
                    return 0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low), exitComment
            elif trade['daysOpen'] == 1:
                exitComment = exitComment + " Exit pattern: " + chartDict['d'][-2].to_string() + "-" + chartDict['d'][-1].to_string()
                if isLastDayBeforeER:
                    if trade['direction'] == util.TickerStatus.LONG:
                        return max(trade['entryPrice'], chartDict['d'][-1].close), exitComment
                    else:
                        return min(trade['entryPrice'], chartDict['d'][-1].close), exitComment
                else:
                    return trade['entryPrice'], exitComment
            else:
                exitComment = exitComment + " Exit pattern: " + chartDict['d'][-2].to_string() + "-" + chartDict['d'][-1].to_string()
                if isLastDayBeforeER:
                    if trade['direction'] == util.TickerStatus.LONG:
                        return max(chartDict['d'][-2].low, chartDict['d'][-1].close), exitComment
                    else:
                        return min(chartDict['d'][-2].high, chartDict['d'][-1].close), exitComment
                else:
                    if trade['direction'] == util.TickerStatus.LONG:
                        return chartDict['d'][-2].low, exitComment
                    else:
                        return chartDict['d'][-2].high, exitComment
        else:
            raise ValueError(f"Strategy {self.name} not implemented in BackTestStrategy")