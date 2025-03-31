import util
class BackTestStrategy:
    
    def __init__(self, name=""):
        self.name = name
        self.ignoreIfGap = True

    # This function returns the trigger price, stop price, and direction of the trade. If gaps are allowed - then the trigger price is the open price of the current candle
    def getNewTrade(self, chartDict):
        
        # SimpleDailyAS strategy: if AS on D in force + TFC on D, W, M (taken at trigger price)
        # Actionable signals: 1-2, 2-2 reversal (so 2u-2d or 2d-2u). Gap over/under trigger should be ignored
        if self.name == "SimpleDailyAS":
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
                return chartDict['d'][-2].high, stopPrice, util.TickerStatus.LONG
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
                return chartDict['d'][-2].low, stopPrice, util.TickerStatus.SHORT
            else:
                return None, None, None
        else:
            raise ValueError(f"Strategy {self.name} not implemented in BackTestStrategy")
            
            
    def getStop(self, chartDict, trade):
        if self.name == "SimpleDailyAS":
            # SimpleDailyAS strategy: 
            # If trade is open at the same day stop is 50% of trigger (previous) candle --> not covered by this function since we assume we are not stopped out at least at the day of entry
            # If trade is open in the previous day - stop is breakeven
            # If trade is open before previous day - stop is at low (long) or high (short) of previous candle
            if trade['daysOpen'] == 0:
                return 0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low)
            elif trade['daysOpen'] == 1:
                return trade['entryPrice']
            else:
                if trade['direction'] == util.TickerStatus.LONG:
                    return chartDict['d'][-2].low
                else:
                    return chartDict['d'][-2].high
        else:
            raise ValueError(f"Strategy {self.name} not implemented in BackTestStrategy")