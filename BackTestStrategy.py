import util
import pandas as pd
class BackTestStrategy:
    
    def __init__(self, name=""):
        self.name = name
        self.ignoreIfGap = True

    # This function returns a list of tuples, with each tuple consisting of the trigger price and direction of the trade
    #   chartDictNew - dictionary with new chart data (including this day candle which may trigger a trade)
    #   chartDictOld - dictionary with old chart data (up to and including previous day candle)
    #   intradayCandles - list of intraday (1min) candles for the current day
    #   firstCandleID - the ID of the first candle to start looking for entry from (needed to support multiple entries in the same day)
    def getNewTrade(self, chartDictNew, chartDictOld, intradayCandles = None, firstCandleID = 0):
        validTrade = False
        tradeListToReturn = []
        # SimpleDailyAS strategy: if AS on D in force + TFC on D, W, M (taken at trigger price)
        # Actionable signals: 1-2, 2-2 reversal (so 2u-2d or 2d-2u). Gap over/under trigger should be ignored
        if self.name == "SimpleDailyAS" or self.name == "SimpleAS_DailyTFCStop" or self.name == "SimpleAS_DailyTFCOrPCTStop":
            if (    # bullish
                # Previous candle is 1 or 2d (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") and
                # Check TFC - previous D high is the trigger price, should be greater than open on the most recent D/W/M candles. 
                # Note that checking D continuity also ensures no gap over trigger
                (chartDictNew['d'][-1].open <= chartDictNew['d'][-2].high) and
                (chartDictNew['w'][-1].open <= chartDictNew['d'][-2].high) and
                (chartDictNew['m'][-1].open <= chartDictNew['d'][-2].high)
            ):
                triggerPrice = chartDictNew['d'][-2].high
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction))
            if (  # bearish
                # Previous candle is 1 or 2u (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") and
                # Check TFC - previous D low is the trigger price. Note that checking D continuity also ensures no gap under trigger
                (chartDictNew['d'][-1].open >= chartDictNew['d'][-2].low) and
                (chartDictNew['w'][-1].open >= chartDictNew['d'][-2].low) and
                (chartDictNew['m'][-1].open >= chartDictNew['d'][-2].low)
            ):
                triggerPrice = chartDictNew['d'][-2].low
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction))
        # LTF entry on HTF signal strategy: Daily AS while W, M, or Q is in force + green TFC on D/W/M 
        elif self.name == "LTFEntryOnHTFSignal":
            if (    # bullish
                # Previous daily candle is 1 or 2d (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") and
                # Check for AS in force on W, M, or Q: 1-2u, 2d-2u, 1-3, 2d-3. Use previous day high as trigger price
                (
                 ((chartDictNew['w'][-2].get_kind() == "2" and chartDictNew['w'][-2].get_subtype() == "D") or chartDictNew['w'][-2].get_kind() == "1" and chartDictNew['d'][-2].high > chartDictNew['w'][-2].high) or
                 ((chartDictNew['m'][-2].get_kind() == "2" and chartDictNew['m'][-2].get_subtype() == "D") or chartDictNew['m'][-2].get_kind() == "1" and chartDictNew['d'][-2].high > chartDictNew['m'][-2].high) or
                 ((chartDictNew['q'][-2].get_kind() == "2" and chartDictNew['q'][-2].get_subtype() == "D") or chartDictNew['q'][-2].get_kind() == "1" and chartDictNew['d'][-2].high > chartDictNew['q'][-2].high)
                ) and
                # Check TFC - previous D high is the trigger price, should be greater than open on the most recent D/W/M candles. 
                # Note that checking D continuity also ensures no gap over trigger
                (chartDictNew['d'][-1].open <= chartDictNew['d'][-2].high) and
                (chartDictNew['w'][-1].open <= chartDictNew['d'][-2].high) and
                (chartDictNew['m'][-1].open <= chartDictNew['d'][-2].high)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].high
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction))
            if (  # bearish
                # Previous daily candle is 1 or 2u (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") and
                # Check for AS in force on W, M, or Q: 1-2d, 2u-2d, 1-3, 2u-3. Use previous day low as trigger price
                (
                 ((chartDictNew['w'][-2].get_kind() == "2" and chartDictNew['w'][-2].get_subtype() == "U") or chartDictNew['w'][-2].get_kind() == "1" and chartDictNew['d'][-2].low < chartDictNew['w'][-2].low) or
                 ((chartDictNew['m'][-2].get_kind() == "2" and chartDictNew['m'][-2].get_subtype() == "U") or chartDictNew['m'][-2].get_kind() == "1" and chartDictNew['d'][-2].low < chartDictNew['m'][-2].low) or
                 ((chartDictNew['q'][-2].get_kind() == "2" and chartDictNew['q'][-2].get_subtype() == "U") or chartDictNew['q'][-2].get_kind() == "1" and chartDictNew['d'][-2].low < chartDictNew['q'][-2].low)
                ) and
                # Check TFC - previous D low is the trigger price. Note that checking D continuity also ensures no gap under trigger
                (chartDictNew['d'][-1].open >= chartDictNew['d'][-2].low) and
                (chartDictNew['w'][-1].open >= chartDictNew['d'][-2].low) and
                (chartDictNew['m'][-1].open >= chartDictNew['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].low
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction))
        # HammerShooterInsideDayAS strategy: AS on D hammer/shooter or inside day (1-2u, 1-3, 2d hammer - 2u, 2d hammer - 3) + no TFC check
        elif self.name == "HammerShooterInsideDayAS":
            if (    # bullish
                # Previous daily candle is 1 or 2d hammer (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D" and chartDictNew['d'][-2].get_pattern == "H") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") and
                # Ensure no gap over trigger
                (chartDictNew['d'][-1].open <= chartDictNew['d'][-2].high) 
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].high
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction))
            if (  # bearish
                # Previous daily candle is 1 or 2u shooter (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U" and chartDictNew['d'][-2].get_pattern == "S") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") and
                # Ensure no gap under trigger
                (chartDictNew['d'][-1].open >= chartDictNew['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].low
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction))
        elif self.name == "HammerShooterInsideDayAS_WithGaps":
            if (    # bullish
                # Previous daily candle is 1 or 2d hammer (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D" and chartDictNew['d'][-2].get_pattern == "H") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") 
            ):
                validTrade = True
                if chartDictNew['d'][-2].high > chartDictNew['d'][-1].open:
                    triggerPrice = chartDictNew['d'][-2].high
                else:   # if gap over trigger
                    triggerPrice = chartDictNew['d'][-1].open
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction))                
            if (  # bearish
                # Previous daily candle is 1 or 2u shooter (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U" and chartDictNew['d'][-2].get_pattern == "S") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") 
            ):
                validTrade = True
                if chartDictNew['d'][-2].low < chartDictNew['d'][-1].open:
                    triggerPrice = chartDictNew['d'][-2].low
                else:   # if gap under trigger
                    triggerPrice = chartDictNew['d'][-1].open
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction))
         # LTFEntryOnHTFSignal_V2 strategy: Daily AS while W, M, or Q is in force + green TFC on D/W/M + no W, M, and Q AS against in force
        elif self.name == "LTFEntryOnHTFSignal_V2":
            if (    # bullish
                # Previous daily candle is 1 or 2d (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") and
                # Check for AS in force on W, M, or Q: 1-2u, 2d-2u, 1-3, 2d-3. Use previous day high as trigger price
                (
                 ((chartDictNew['w'][-2].get_kind() == "2" and chartDictNew['w'][-2].get_subtype() == "D") or chartDictNew['w'][-2].get_kind() == "1" and chartDictNew['d'][-2].high > chartDictNew['w'][-2].high) or
                 ((chartDictNew['m'][-2].get_kind() == "2" and chartDictNew['m'][-2].get_subtype() == "D") or chartDictNew['m'][-2].get_kind() == "1" and chartDictNew['d'][-2].high > chartDictNew['m'][-2].high) or
                 ((chartDictNew['q'][-2].get_kind() == "2" and chartDictNew['q'][-2].get_subtype() == "D") or chartDictNew['q'][-2].get_kind() == "1" and chartDictNew['d'][-2].high > chartDictNew['q'][-2].high)
                ) and
                # Check for AS not in force on W, M, or Q: it means trigger price is higher than previous W/M/Q low. Use previous day high as trigger price
                ((chartDictNew['d'][-2].high > chartDictNew['w'][-2].low) and
                 (chartDictNew['d'][-2].high > chartDictNew['m'][-2].low) and
                 (chartDictNew['d'][-2].high > chartDictNew['q'][-2].low)) and
                # Check TFC - previous D high is the trigger price, should be greater than open on the most recent D/W/M candles. 
                # Note that checking D continuity also ensures no gap over trigger
                (chartDictNew['d'][-1].open <= chartDictNew['d'][-2].high) and
                (chartDictNew['w'][-1].open <= chartDictNew['d'][-2].high) and
                (chartDictNew['m'][-1].open <= chartDictNew['d'][-2].high)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].high
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction))
            if (  # bearish
                # Previous daily candle is 1 or 2u (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") and
                # Check for AS in force on W, M, or Q: 1-2d, 2u-2d, 1-3, 2u-3. Use previous day low as trigger price
                (
                 ((chartDictNew['w'][-2].get_kind() == "2" and chartDictNew['w'][-2].get_subtype() == "U") or chartDictNew['w'][-2].get_kind() == "1" and chartDictNew['d'][-2].low < chartDictNew['w'][-2].low) or
                 ((chartDictNew['m'][-2].get_kind() == "2" and chartDictNew['m'][-2].get_subtype() == "U") or chartDictNew['m'][-2].get_kind() == "1" and chartDictNew['d'][-2].low < chartDictNew['m'][-2].low) or
                 ((chartDictNew['q'][-2].get_kind() == "2" and chartDictNew['q'][-2].get_subtype() == "U") or chartDictNew['q'][-2].get_kind() == "1" and chartDictNew['d'][-2].low < chartDictNew['q'][-2].low)
                ) and
                # Check for AS not in force on W, M, or Q: it means trigger price is lower than previous W/M/Q high. Use previous day high as trigger price
                ((chartDictNew['d'][-2].low < chartDictNew['w'][-2].high) and
                 (chartDictNew['d'][-2].low < chartDictNew['m'][-2].high) and
                 (chartDictNew['d'][-2].low < chartDictNew['q'][-2].high)) and
                # Check TFC - previous D low is the trigger price. Note that checking D continuity also ensures no gap under trigger
                (chartDictNew['d'][-1].open >= chartDictNew['d'][-2].low) and
                (chartDictNew['w'][-1].open >= chartDictNew['d'][-2].low) and
                (chartDictNew['m'][-1].open >= chartDictNew['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].low
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction))
        # BasicDailyAS strategy: simply AS on D: 1-2u, 1-3, 2d-2u, 2d-3 (this is mainly used for data collection)
        elif self.name == "BasicDailyAS":
            if (    # bullish
                # Previous candle is 1 or 2d (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") and
                # Ensure no gap over trigger
                (chartDictNew['d'][-1].open <= chartDictNew['d'][-2].high)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].high
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction))
            if (  # bearish
                # Previous candle is 1 or 2u (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") and
                # Ensure no gap under trigger
                (chartDictNew['d'][-1].open >= chartDictNew['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].low
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction))
        elif self.name == "DailyTrigAndTarget":
            if len(chartDictNew['d']) < 3:
                return tradeListToReturn
            # Daily AS with trigger and target. 1-2u, 1-3, 2d-2u, 2d-3 for bullish. Only pick trades with R:R > 3
            if (    # bullish
                # Previous candle is 1 or 2d (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3") and
                # Ensure no gap over trigger
                (chartDictNew['d'][-1].open <= chartDictNew['d'][-2].high)
                # Check R:R > 3
                #chartDictNew['d'][-3].high - chartDictNew['d'][-2].high > 3 * (chartDictNew['d'][-2].high - chartDictNew['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].high
                targetPrice = chartDictNew['d'][-3].high
                direction = util.TickerStatus.LONG
                tradeListToReturn.append((triggerPrice, direction, targetPrice))
            if (  # bearish
                # Previous candle is 1 or 2u (bearish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "U") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current candle is 2d (bearish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "D") or chartDictNew['d'][-1].get_kind() == "3") and
                # Ensure no gap under trigger
                (chartDictNew['d'][-1].open >= chartDictNew['d'][-2].low) 
                # Check R:R > 3
                #chartDictNew['d'][-2].low - chartDictNew['d'][-3].low > 3 * (chartDictNew['d'][-2].high - chartDictNew['d'][-2].low)
            ):
                validTrade = True
                triggerPrice = chartDictNew['d'][-2].low
                targetPrice = chartDictNew['d'][-3].low
                direction = util.TickerStatus.SHORT
                tradeListToReturn.append((triggerPrice, direction, targetPrice))
        elif self.name == "StratLab2dGM":
            if len(chartDictNew['d']) < 3 or len(chartDictNew['m']) < 2:
                return tradeListToReturn
            # Daily AS with 2dG Month. 1-2u, 1-3, 2d-2u, 2d-3 for bullish. Bullish only
            if (    # bullish
                # Previous daily candle is 1 or 2d (bullish)
                ((chartDictNew['d'][-2].get_kind() == "2" and chartDictNew['d'][-2].get_subtype() == "D") or chartDictNew['d'][-2].get_kind() == "1") and
                # Current daily candle is 2u (bullish) or 3 (case when we break in the right direction first, then reverse is handled by checking for stop at day of entry)
                ((chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U") or chartDictNew['d'][-1].get_kind() == "3")
               ):
                triggerPrice = max(chartDictNew['d'][-2].high, chartDictNew['d'][-1].open)
                direction = util.TickerStatus.LONG
                if intradayCandles is None: # this is helpful for screening purposes when intraday candles are not yet available
                    tradeListToReturn.append((triggerPrice, direction))
                else:
                    # Knowing trigger price, check for 2dG Month
                    entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high > triggerPrice), None)
                    if not (entryID is None):
                        monthLow = min(candle.low for candle in intradayCandles[:entryID+1]) # this day low is equal to M low if this day is the first day of the month
                        if chartDictOld['m'][-1].open_ts == chartDictNew['m'][-1].open_ts: # this day belongs to the same month candle
                            monthLow = min(monthLow, chartDictOld['m'][-1].low)
                        # Check for 2d and Green Month
                        if (monthLow < chartDictNew['m'][-2].low and        # check for 2d Month
                            chartDictNew['m'][-1].open < triggerPrice):     # check for Green Month
                            direction = util.TickerStatus.LONG
                            tradeListToReturn.append((triggerPrice, direction))
        else:
            raise ValueError(f"Strategy {self.name} not implemented in BackTestStrategy")
        
        
            '''
            # Build list of candle combos at each timeframe 
            entry_comment = ("D: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string() + 
                " W: " + chartDictNew['w'][-2].to_string() + "-" + chartDictNew['w'][-1].to_string() + 
                " M: " + chartDictNew['m'][-2].to_string() + "-" + chartDictNew['m'][-1].to_string() + 
                " Q: " + chartDictNew['q'][-2].to_string() + "-" + chartDictNew['q'][-1].to_string() +
                " Y: " + chartDictNew['y'][-2].to_string() + "-" + chartDictNew['y'][-1].to_string() +"||")
            # Determine TFC
            for tf in ['d', 'w', 'm', 'q', 'y']:
                if triggerPrice > chartDictNew[tf][-1].open:
                    entry_comment += "G|"
                else:
                    entry_comment += "R|"
            '''

        return tradeListToReturn

    # This function is used to find potential trades based on daily chart before intraday candles are requested
    #   chartDictNew - dictionary with new chart data (including this day candle which may trigger a trade)
    #   chartDictOld - dictionary with old chart data (up to and including previous day candle)
    def screenTrade(self, chartDictNew, chartDictOld): 
        result = self.getNewTrade(chartDictNew, chartDictOld)
        if len(result) > 0:
            return True
        else:
            return False
    #   chartDictNew - dictionary with new chart data (including this day candle which may trigger a stop)
    #   chartDictOld - dictionary with old chart data (up to and including previous day candle)
    def getStop(self, chartDictNew, chartDictOld, trade, intradayCandles = None, entryID = 0):
        exitComment = ""
        if self.name == "SimpleDailyAS":
            # SimpleDailyAS strategy: 
            # If trade is open at the same day stop is 50% of trigger (previous) candle 
            # If trade is open in the previous day - stop is breakeven
            # If trade is open before previous day - stop is at low (long) or high (short) of previous candle
            if trade['daysOpen'] == 0:
                    return 0.5*(chartDictNew['d'][-2].high+chartDictNew['d'][-2].low), exitComment
            elif trade['daysOpen'] == 1:
                exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
                return trade['entryPrice'], exitComment
            else:
                exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
                if trade['direction'] == util.TickerStatus.LONG:
                    return chartDictNew['d'][-2].low, exitComment
                else:
                    return chartDictNew['d'][-2].high, exitComment
        elif self.name == "SimpleAS_DailyTFCStop":
            # Same as SimpleDailyAS strategy but with extra stop at Day 0 if Daily TFC flips
            # If trade is open at the same day stop is 50% of trigger (previous) candle 
            # If trade is open in the previous day - stop is breakeven
            # If trade is open before previous day - stop is at low (long) or high (short) of previous candle
            if trade['daysOpen'] == 0:
                if trade['direction'] == util.TickerStatus.LONG:
                    return max(0.5*(chartDictNew['d'][-2].high+chartDictNew['d'][-2].low), chartDictNew['d'][-1].open), exitComment
                else:
                    return min(0.5*(chartDictNew['d'][-2].high+chartDictNew['d'][-2].low), chartDictNew['d'][-1].open), exitComment
            elif trade['daysOpen'] == 1:
                exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
                return trade['entryPrice'], exitComment
            else:
                exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
                if trade['direction'] == util.TickerStatus.LONG:
                    return chartDictNew['d'][-2].low, exitComment
                else:
                    return chartDictNew['d'][-2].high, exitComment
        elif self.name == "SimpleAS_DailyTFCOrPCTStop":
            # Same as SimpleDailyAS strategy but with extra stop at Day 0 if Daily TFC flips or if stop loss exceeds 1%
            # If trade is open at the same day stop is 50% of trigger (previous) candle 
            # If trade is open in the previous day - stop is breakeven
            # If trade is open before previous day - stop is at low (long) or high (short) of previous candle
            fixed_stop = 0.01  # stop loss percentage
            if trade['daysOpen'] == 0:
                #exitComment = exitComment + " Stop 0.5%"
                if trade['direction'] == util.TickerStatus.LONG:
                    return max(0.5*(chartDictNew['d'][-2].high+chartDictNew['d'][-2].low), chartDictNew['d'][-1].open, (1-fixed_stop)*trade['entryPrice']), exitComment
                else:
                    return min(0.5*(chartDictNew['d'][-2].high+chartDictNew['d'][-2].low), chartDictNew['d'][-1].open, (1+fixed_stop)*trade['entryPrice']), exitComment
            elif trade['daysOpen'] == 1:
                exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
                return trade['entryPrice'], exitComment
            else:
                exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
                if trade['direction'] == util.TickerStatus.LONG:
                    return chartDictNew['d'][-2].low, exitComment
                else:
                    return chartDictNew['d'][-2].high, exitComment
        # Strategies: LTF entry on HTF signal strategy; HammerShooterInsideDayAS; BasicDailyAS. Stop at Daily AS against 
        elif (self.name == "LTFEntryOnHTFSignal" or 
              self.name == "LTFEntryOnHTFSignal_V2" or
              self.name == "HammerShooterInsideDayAS" or
              self.name == "HammerShooterInsideDayAS_WithGaps" or
              self.name == "BasicDailyAS"
            ):
            exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
            if trade['direction'] == util.TickerStatus.LONG:
                return chartDictNew['d'][-2].low, exitComment
            else:
                return chartDictNew['d'][-2].high, exitComment
        elif self.name == "DailyTrigAndTarget":
            exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
            if trade['daysOpen'] == 0:
                if trade['direction'] == util.TickerStatus.LONG:
                    trade['stop'] = chartDictNew['d'][-2].low
                else:
                    trade['stop'] = chartDictNew['d'][-2].high
            return trade['stop'], exitComment
        elif self.name == "StratLab2dGM":
            exitComment = exitComment + "Exit pattern: " + chartDictNew['d'][-2].to_string() + "-" + chartDictNew['d'][-1].to_string()
            if trade['direction'] == util.TickerStatus.LONG:
                if trade['daysOpen'] == 0:
                    if intradayCandles is None:
                        # live trading: live daily candle already tracks the running intraday low
                        trade['stop'] = chartDictNew['d'][-1].low
                    else:
                        trade['stop'] = min(candle.low for candle in intradayCandles[:entryID+1])    # low of day on the day of entry
                elif trade['daysOpen'] >= 2:
                    trade['stop'] = max(trade['stop'], trade['entryPrice'], chartDictNew['d'][-2].low)  # move stop up to previous D low or entry price, whichever is higher
                elif trade['daysOpen'] == 1:
                    if chartDictNew['d'][-1].get_kind() == "2" and chartDictNew['d'][-1].get_subtype() == "U" and chartDictNew['d'][-1].get_direction() == "R" :   # if 2u red day on Day 1 - exit end of day
                        trade['stop'] = chartDictNew['d'][-1].close + 0.01  # we add 0.01 to ensure stop is triggered 
                return trade['stop'], exitComment
        else:
            raise ValueError(f"Strategy {self.name} not implemented in BackTestStrategy")
    # In general this can be modified for each strategy, but for now it is the same for all. If trade is active - close at end of day
    def handleER(self, trade, chartDict):
        exitComment = f"ER day - {pd.to_datetime(chartDict['d'][-1].open_ts, unit='s', utc=True).date()}| "
        if trade['exitPrice'] == -1:    # Trade is still open
            exitComment += "Close at end of day| "
            # If trade is active - close at end of day
            trade['exitPrice'] = chartDict['d'][-1].close
            trade['exitTimestamp_sec'] = chartDict['d'][-1].open_ts
            trade['exit_comment'] = exitComment

