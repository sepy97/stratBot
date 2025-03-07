from datetime import datetime, timedelta
#import session
import alpaca_chart
import util
import pandas as pd
import MarketTimeManager as mtm
import os

# TODO: ALL TIMESTAMPS ARE IN SECONDS, NOT MILLISECONDS - RESPECTIVE KEYS NEED TO BE UPDATED
# Assumes candle1 is candle at T-2, candle2 is candle at T-1
def isAS(candle1, candle2, direction):
    return (direction == util.TickerStatus.LONG and candle1['high'] > candle2['high']) or \
    (direction == util.TickerStatus.SHORT and candle1['low'] < candle2['low'])

'''
# Assumes candle1 is candle at T-1, candle0 is current candle
def enterTrade(sym, candle1, candle0, direction, session):
    tradeToReturn =[]

    # Find trigger price
    if (direction == util.TickerStatus.LONG):
        triggerPrice = candle1['high']
    else:
        triggerPrice = candle1['low']

    # check if never triggered or gap over trigger (if true then skip entering trade)
    if (direction == util.TickerStatus.LONG and (candle0['high'] <= triggerPrice or candle0['open'] > triggerPrice)) or \
    (direction == util.TickerStatus.SHORT and (candle0['low'] >= triggerPrice or candle0['open'] < triggerPrice)):
        tradeToReturn =[]
    else:
        #lastCandleTime = datetime.fromtimestamp(candle0['datetime']/1000).replace(hour = 0) + timedelta(days = 1) # TD returns previous day 10pm as timestamp for daily candle
        lastCandleTime = datetime.fromtimestamp(candle0['datetime']).replace(hour = 0) + timedelta(days = 1) # TD returns previous day 10pm as timestamp for daily candle; Alpaca return previous day 9pm
        openCloseTimestamp_ms = util.getOpenCloseAtDay(datetime.timestamp(lastCandleTime)*1000)
        #intradayData = session.get_price_history(symbol=sym, period_type="day", period=None, frequency_type="minute", frequency=1, start_date=openCloseTimestamp_ms['open'], end_date=openCloseTimestamp_ms['close'], extended_hours=False)
        #intradayCandles = intradayData['candles']
        intradayCandles = alpaca_chart.getChart(session, sym, 'm1', openCloseTimestamp_ms['open']/1000, openCloseTimestamp_ms['close']/1000-1)
        ii = 0
        while(ii < len(intradayCandles) and \
              ((direction == util.TickerStatus.LONG and intradayCandles[ii]['high'] <= triggerPrice) or \
              (direction == util.TickerStatus.SHORT and intradayCandles[ii]['low'] >= triggerPrice))):
            ii = ii + 1
        if ii == len(intradayCandles):  # this should never happen
            print('no entry found intraday but expected an entry based on daily chart')
            tradeToReturn = []
        else:   # enter trade
            entryTimestamp = intradayCandles[ii]['datetime']
            # check if stop out the same day (for efficiency, so we don't pull the same 1min data from API again)
            stopPrice = 0.5*(candle1['high']+candle1['low'])
            ii = ii + 1
            while (ii < len(intradayCandles) and \
                ((direction == util.TickerStatus.LONG and intradayCandles[ii]['low'] >= stopPrice) or \
                (direction == util.TickerStatus.SHORT and intradayCandles[ii]['high'] <= stopPrice))):
                ii = ii + 1
            exitPrice = -1
            exitTimestamp = -1
            daysOpen = 1
            if ii < len(intradayCandles): # stopped the same day
                exitPrice = stopPrice
                exitTimestamp = intradayCandles[ii]['datetime']
                daysOpen = 0
            tradeToReturn = {'symbol': sym, 'entryPrice': triggerPrice, 'entryTimestamp_ms': entryTimestamp, \
                         'stop': triggerPrice, 'exitPrice': exitPrice, 'exitTimestamp_ms': exitTimestamp, \
                         'daysOpen': daysOpen, 'direction': direction}
#newTrade = {'symbol': symbol, 'entryPrice': entryPrice, 'entryTimestamp': entryTimestamp, 'stop': stopPrice, 'exitPrice': exitPrice, 'exitTimestamp': exitTimestamp, 'daysOpen': 0, 'direction': direction}
    return tradeToReturn
'''
# Strategy will be defined here
def enterTrade(sym, chartDict, session):
    tradeToReturn = []
    exitPrice = -1
    exitTimestamp = -1
    daysOpen = 1
    # Strategy: if AS on D in force, price at trigger > prev W high and previous M high + TFC on D, W, M (taken at trigger price)
    # Actionable signals: 1-2, 2-2 reversal (so 2u-2d or 2d-2u). Single day rev-strat (1-3) - not implemented. Gap over trigger should be ignored
    # Bullish version
    if  (
        # Previous candle is 1 or 2d
        ((chartDict['d'][-2].get_kind() == "2" and chartDict['d'][-2].get_subtype() == "D") or chartDict['d'][-2].get_kind() == "1") and
        # Current candle is 2u or 3 (need to handle case when we break higher first, then reverse)
        chartDict['d'][-1].high >  chartDict['d'][-2].high and
        # Check TFC - previous D high is the trigger price
        chartDict['d'][-1].open < chartDict['d'][-2].high and chartDict['w'][-1].open < chartDict['d'][-2].high and chartDict['m'][-1].open < chartDict['d'][-2].high):
        direction = util.TickerStatus.LONG
        triggerPrice = chartDict['d'][-2].high
        # Check if gap over trigger (if true then skip entering trade); otherwise get intraday chart and find the exact time of entry
        if chartDict['d'][-1].open <= triggerPrice:
            #tradeDay = pd.to_datetime(chartDict['d'][-1].open_ts, unit='s').date()
            #intradayCandles = alpaca_chart.getChart(session, sym, 'm1', tradeDay, tradeDay)
            tradeDay = mtm.getCandleOpenCloseTime(chartDict['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
            intradayCandles = alpaca_chart.getChart(session, sym, 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
            entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high > triggerPrice), None)
            if entryID is None:
                print(f'No long entry found intraday but expected an entry based on daily chart on {tradeDay[0]}')
                return tradeToReturn
            else:   # enter trade
                entryTimestamp = intradayCandles[entryID].open_ts

            #ii = 0
            #while (ii < len(intradayCandles) and (intradayCandles[ii].high <= triggerPrice)):
            #    ii = ii + 1
            #if ii == len(intradayCandles):  # this should never happen
            #    print(f'No long entry found intraday but expected an entry based on daily chart on {tradeDay[0]}')
            #    return tradeToReturn
            #else:   # enter trade
            #    entryTimestamp = intradayCandles[ii].open_ts
            # check if stop out the same day (for efficiency, so we don't pull the same 1min data from API again)
            stopPrice = 0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low)
            exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if candle.low < stopPrice), None)
            #ii = ii + 1
            #while (ii < len(intradayCandles) and (intradayCandles[ii].low >= stopPrice)):
            #    ii = ii + 1
            #if ii < len(intradayCandles): # stopped the same day
            if not exitID is None:
                exitPrice = stopPrice
                exitTimestamp = intradayCandles[exitID].open_ts
                daysOpen = 0
            tradeToReturn = {'symbol': sym, 'entryPrice': triggerPrice, 'entryTimestamp_ms': entryTimestamp, 
                         'stop': triggerPrice, 'exitPrice': exitPrice, 'exitTimestamp_ms': exitTimestamp, 
                         'daysOpen': daysOpen, 'direction': direction}
    # Bearish version
    elif (
        # Previous candle is 1 or 2u
        ((chartDict['d'][-2].get_kind() == "2" and chartDict['d'][-2].get_subtype() == "U") or chartDict['d'][-2].get_kind() == "1") and
        # Current candle is 2d or 3 (need to handle case when we break lower first, then reverse)
        chartDict['d'][-1].low <  chartDict['d'][-2].low and
        # Check TFC - previous D low is the trigger price
        chartDict['d'][-1].open > chartDict['d'][-2].low and chartDict['w'][-1].open > chartDict['d'][-2].low and chartDict['m'][-1].open > chartDict['d'][-2].low):
        # Find trigger price
        direction = util.TickerStatus.SHORT
        triggerPrice = chartDict['d'][-2].low
        # Check if gap under trigger (if true then skip entering trade); otherwise get intraday chart and find the exact time of entry
        if chartDict['d'][-1].open >= triggerPrice:
            #tradeDay = pd.to_datetime(chartDict['d'][-1].open_ts, unit='s').date()
            tradeDay = mtm.getCandleOpenCloseTime(chartDict['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
            intradayCandles = alpaca_chart.getChart(session, sym, 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
            
            entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.low < triggerPrice), None)
            if entryID is None:
                print(f'No short entry found intraday but expected an entry based on daily chart on {tradeDay[0]}')
                return tradeToReturn
            else:   # enter trade
                entryTimestamp = intradayCandles[entryID].open_ts
            #while (ii < len(intradayCandles) and intradayCandles[ii].low >= triggerPrice):
            #    ii = ii + 1
            #if ii == len(intradayCandles):  # this should never happen
            #    print(f'No short entry found intraday but expected an entry based on daily chart on {tradeDay[0]}')
            #    return tradeToReturn
            #else:   # enter trade
            #    entryTimestamp = intradayCandles[ii].open_ts
            # check if stop out the same day (for efficiency, so we don't pull the same 1min data from API again)
            stopPrice = 0.5*(chartDict['d'][-2].high+chartDict['d'][-2].low)
            exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if candle.high > stopPrice), None)

            #ii = ii + 1
            #while (ii < len(intradayCandles) and intradayCandles[ii].high <= stopPrice):
            #    ii = ii + 1
            #if ii < len(intradayCandles): # stopped the same day
            if not exitID is None:
                exitPrice = stopPrice
                exitTimestamp = intradayCandles[exitID].open_ts
                daysOpen = 0
            tradeToReturn = {'symbol': sym, 'entryPrice': triggerPrice, 'entryTimestamp_ms': entryTimestamp,
                         'stop': triggerPrice, 'exitPrice': exitPrice, 'exitTimestamp_ms': exitTimestamp,
                         'daysOpen': daysOpen, 'direction': direction}

    return tradeToReturn
# check if stop is hit. If stop hit - set exit price and timestamp; otherwise - update stop 
def updateTrade(trade, lastCandle, direction, session):
    if  ((trade.direction == util.TickerStatus.LONG and lastCandle['low'] > trade['stop']) or
        (direction == util.TickerStatus.SHORT and lastCandle['high'] <= trade['stop'])):
        trade['daysOpen'] = trade['daysOpen'] + 1
        trade['stop'] = getNewStop(trade, lastCandle, direction)

    else:   # find time when stop hit, also check if we gapped stop
        lastCandleTime = datetime.fromtimestamp(lastCandle['datetime']).replace(hour = 0) + timedelta(days = 1) # TD returns previous day 10pm as timestamp for daily candle; Alpaca return previous day 9pm
        openCloseTimestamp_ms = util.getOpenCloseAtDay(datetime.timestamp(lastCandleTime)*1000)
        #startTimestamp_ms = max(trade['entryTimestamp_ms'], openCloseTimestamp_ms['open'])
        #intradayData = session.get_price_history(symbol=trade['symbol'], period_type="day", period=None, frequency_type="minute", frequency=1, start_date=openCloseTimestamp_ms['open'], end_date=openCloseTimestamp_ms['close'], extended_hours=False)
        #intradayCandles = intradayData['candles']
        intradayCandles = alpaca_chart.getChart(session, trade['symbol'], 'm1', openCloseTimestamp_ms['open']/1000, openCloseTimestamp_ms['close']/1000-1)
        ii = 0
        while ((direction == util.TickerStatus.LONG and intradayCandles[ii]['low'] >= trade['stop']) or \
            (direction == util.TickerStatus.SHORT and intradayCandles[ii]['high'] <= trade['stop'])) and \
            ii < len(intradayCandles):
            ii = ii + 1
        if ii == len(intradayCandles):  # this should never happen, print error and stop out at stop price
            print('no exit found intraday but expected an exit based on daily chart')
            trade['exitPrice'] = trade['stop']
            #trade['daysOpen'] = trade['daysOpen'] + 1
            #trade['stop'] = getNewStop(trade, lastCandle, direction)
        else:   # stop hit, record exit price and time
            if (direction == util.TickerStatus.LONG and intradayCandles[ii]['open'] < trade['stop']) or \
            (direction == util.TickerStatus.SHORT and intradayCandles[ii]['open'] > trade['stop']): # if the price gapped through stop
                trade['exitPrice'] = intradayCandles[ii]['open']
            else:
                trade['exitPrice'] = trade['stop']
            trade['exitTimestamp_ms'] = intradayCandles[ii]['datetime']

# Compute stop assuming lastCandle did not trigger stop
# If trade is open at the same day stop is 50% of trigger candle --> not covered by this function since we assume we are not stopped out at least at the day of entry
# If trade is open in the previous day - stop is breakeven
# If trade is open before previous day - stop is at low (long) or high (short) of previous candle       
def getNewStop(trade, lastCandle, direction):
    if trade['daysOpen'] == 1:
        return trade['entryPrice']
    else:
        if direction == util.TickerStatus.LONG:
            return lastCandle['low']
        else:
            return lastCandle['high']

def printTrade(trade):
    #tradeToReturn = {'symbol': symbol, 'entryPrice': triggerPrice, 'entryTimestamp_ms': intradayCandles[ii]['datetime'], \
    #         'stop': 0.5*(candle1['high']+candle1['low']), 'exitPrice': -1, 'exitTimestamp_ms': -1, \
    #         'daysOpen': 0, 'direction': direction}
    entryTime = datetime.fromtimestamp(trade['entryTimestamp_ms'])
    gain_pct = 0
    if trade['exitTimestamp_ms'] == -1:
        exitTime = 'NA'
    else:
        exitTime = datetime.fromtimestamp(trade['exitTimestamp_ms'])
    if (trade['direction'] == util.TickerStatus.LONG):
        dir = 'Long'
        gain_pct = 100*(trade['exitPrice']/trade['entryPrice']-1)
    else:
        dir = 'Short'
        gain_pct = 100*(1- trade['exitPrice']/trade['entryPrice'])
    print("----------\n")
    print('Symbol: ' + trade['symbol'] + '\n')
    print('Entered: ' + dir + ' at ' + str(trade['entryPrice']) + ' on ' + entryTime.__str__() + '\n')
    print('Exited: ' + ' at ' + str(trade['exitPrice']) + ' on ' + exitTime.__str__() + '\n')
    print(f"Gain = {gain_pct:.2f}% \n")

def printChart(chart):
    with open('chart.txt', 'a') as f:
        f.write("Chart\n")
        f.write("========================\n")
        for tf in chart.keys():
            f.write(f"Timeframe: {tf}\n")
            for candle in chart[tf]:
                f.write(candle.to_string_full() + '\n')

# This function updates all charts based on new daily candle. Assumes new candle is the next immediate candle after last_day
# Starting chart (chartDict) must have at least one candle for each TF
def addDailyCandleToChart(chartDict, lastDayDate, dayCandleToAdd, dayDateToAdd):
    w = dayDateToAdd.week
    m = dayDateToAdd.month
    q = (m-1)//3
    y = dayDateToAdd.year
    last_w = lastDayDate.week
    last_m = lastDayDate.month
    last_q = (last_m-1)//3
    last_y = lastDayDate.year
    chartDict['d'].append(dayCandleToAdd)
    # Weekly flip
    if w != last_w:
        chartDict['w'].append(dayCandleToAdd)
        chartDict['w'][-1].previous_high = chartDict['w'][-2].high
        chartDict['w'][-1].previous_low = chartDict['w'][-2].low
    else:
        chartDict['w'][-1].high = max(chartDict['w'][-1].high, dayCandleToAdd.high)
        chartDict['w'][-1].low = min(chartDict['w'][-1].low, dayCandleToAdd.low)
        chartDict['w'][-1].close = dayCandleToAdd.close

    # Monthly flip
    if m != last_m:
        chartDict['m'].append(dayCandleToAdd)
        chartDict['m'][-1].previous_high = chartDict['m'][-2].high
        chartDict['m'][-1].previous_low = chartDict['m'][-2].low
    else:
        chartDict['m'][-1].high = max(chartDict['m'][-1].high, dayCandleToAdd.high)
        chartDict['m'][-1].low = min(chartDict['m'][-1].low, dayCandleToAdd.low)
        chartDict['m'][-1].close = dayCandleToAdd.close

    # Quarterly flip
    if q != last_q:
        chartDict['q'].append(dayCandleToAdd)
        chartDict['q'][-1].previous_high = chartDict['q'][-2].high
        chartDict['q'][-1].previous_low = chartDict['q'][-2].low
    else:
        chartDict['q'][-1].high = max(chartDict['q'][-1].high, dayCandleToAdd.high)
        chartDict['q'][-1].low = min(chartDict['q'][-1].low, dayCandleToAdd.low)
        chartDict['q'][-1].close = dayCandleToAdd.close

    # Yearly flip
    if y != last_y:
        chartDict['y'].append(dayCandleToAdd)
        chartDict['y'][-1].previous_high = chartDict['y'][-2].high
        chartDict['y'][-1].previous_low = chartDict['y'][-2].low
    else:
        chartDict['y'][-1].high = max(chartDict['y'][-1].high, dayCandleToAdd.high)
        chartDict['y'][-1].low = min(chartDict['y'][-1].low, dayCandleToAdd.low)
        chartDict['y'][-1].close = dayCandleToAdd.close
    return chartDict

# Backtesting with limited number of queries for candle bars
# Assume that strategy is relying on D and higher TF
# Steps:
#   Get daily candles from startDay-1 to endDay to use later as a source of data (need one more day prior to startDay so we could enter on startDay if conditions are right)
#   Initialize chart on all TFs (D, W, M, Q, Y) at startDay
#   Every new day:
#       Update all charts 
#       Update status of existing trades
#       Check if new trades should be open (AS in force)
if __name__ == "__main__":
    startDay_str = "2024-11-24 6:30:00"
    endDay_str = "2024-12-01 6:30:00"
    timezone = 'America/Los_Angeles'
    symbol = "SPY"

    #TDSession = session.initTDSession()
    trades = []
    session = alpaca_chart.initSession()

    startDay = pd.to_datetime(startDay_str).tz_localize(timezone)
    endDay = pd.to_datetime(endDay_str).tz_localize(timezone)
    startDayToQuery = mtm.getCandleOpenCloseTime(startDay.timestamp(), 'd', n_pre=1, n_post=0)
    startDayToQuery = startDayToQuery['pre'][0]
    # Get daily chart spanning full range of days
    dailyChart = alpaca_chart.getChart(stock_client=session, symbol=symbol, timeframe_sym='d', start_timestamp=startDayToQuery[0].timestamp(), end_timestamp=endDay.timestamp())
    #direction = util.TickerStatus.SHORT
    TF_sym_list = ['d', 'w', 'm', 'q', 'y']
    chartDict = dict.fromkeys(TF_sym_list)
    # Init daily chart (do it separately to save on extra query to Alpaca API)
    chartDict['d'] = [dailyChart[0]]
    # Find the earliest day on or after startDay when market is open and init all other charts
    #startDayMarket = mtm.getCandleOpenCloseTime(startDay.timestamp(), 'd', n_pre=0, n_post=1)
    #if startDayMarket['current'] is None:
    #    startDayMarket = startDayMarket['post'][0]
    #    startDayMarket = startDayMarket[0]
    #else:
    #    startDayMarket = startDayMarket['current'][0]
    # Initialize all higher TF charts (W and higher)
    for TF_sym in TF_sym_list[1:]:
        chartDict[TF_sym] = alpaca_chart.getChart(stock_client=session, symbol=symbol, timeframe_sym=TF_sym, start_timestamp=startDayToQuery[0].timestamp(), end_timestamp=startDayToQuery[1].timestamp())
    lastDay = startDayToQuery[0]
    if os.path.exists('chart.txt'):
        os.remove('chart.txt')
    printChart(chartDict)
    # Start backtesting
    for day_id in range(1, len(dailyChart)):
        # Update charts
        dayCandleToAdd = dailyChart[day_id]
        dayDateToAdd = pd.to_datetime(dayCandleToAdd.open_ts, unit='s')
        chartDict = addDailyCandleToChart(chartDict, lastDay, dayCandleToAdd, dayDateToAdd)
        lastDay = dayDateToAdd
        printChart(chartDict)

        # Update trades
        #for trade in trades:
        #    if trade['exitPrice'] == - 1:
        #        updateTrade(trade, dayCandle, direction, session)

        # Check for new trades
        # Strategy is implemented in enterTrade function
        newTrade = enterTrade(symbol, chartDict, session)
        if bool(newTrade):
            trades.append(newTrade)

            
    # Log resulting trades
    for trade in trades:
        printTrade(trade)

'''
    for ii in range(2, len(candles)):
        for trade in trades:
            if trade['exitPrice'] == - 1: # trade still active
                updateTrade(trade, candles[ii], direction, session)
        if isAS(candles[ii-2], candles[ii-1], direction):
            #try to enter: check for trigger and ensure no gap over trigger
            newTrade = enterTrade(symbol, candles[ii-1], candles[ii], direction, session)
            if bool(newTrade):
                trades.append(newTrade)        
'''
        







