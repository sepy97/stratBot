from datetime import datetime, timedelta
#import session
import alpaca_chart
import util
import pandas as pd
import MarketTimeManager as mtm
import os
import copy
from BackTestStrategy import BackTestStrategy as bts

# TODO: This may or may be needed. Commenting out for now
#def isAS(candle1, candle2, direction):
#    return (direction == util.TickerStatus.LONG and candle1['high'] > candle2['high']) or \
#    (direction == util.TickerStatus.SHORT and candle1['low'] < candle2['low'])

# Function to enter a trade based on the strategy. Returns a dictionary with trade details. If no trade is entered - returns an empty dictionary
def enterTrade(sym, chartDict, session, strategy):
    tradeToReturn = []
    exitPrice = -1
    exitTimestamp = -1
    daysOpen = 0

    triggerPrice, stopPrice, direction = strategy.enterTrade(chartDict)
    if direction is None:
        return tradeToReturn
    elif direction == util.TickerStatus.LONG:
        entryLbl = "long"
    else:
        entryLbl = "short"
    
    # Find the exact time of entry
    tradeDay = mtm.getCandleOpenCloseTime(chartDict['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
    intradayCandles = alpaca_chart.getChart(session, sym, 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
    if direction == util.TickerStatus.LONG:
        entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high > triggerPrice), None)
    else:
        entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.low < triggerPrice), None)
    if entryID is None:
        print(f'No entry found intraday but expected a {entryLbl} entry based on daily chart on {tradeDay[0]}')
        return tradeToReturn
    else:   # record time of entry
        entryTimestamp = intradayCandles[entryID].open_ts

    tradeToReturn = {'symbol': sym, 'entryPrice': triggerPrice, 'entryTimestamp_sec': entryTimestamp, 
                'stop': stopPrice, 'exitPrice': exitPrice, 'exitTimestamp_sec': exitTimestamp, 
                'daysOpen': daysOpen, 'direction': direction}
    
    # Check if stop out the same day (for efficiency, so we don't pull the same 1min data from API again)
    if direction == util.TickerStatus.LONG:
        exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if candle.low < stopPrice), None)
    else:
        exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if candle.high > stopPrice), None)
    if not exitID is None:
        tradeToReturn['exitPrice'] = stopPrice
        tradeToReturn['exitTimestamp_sec'] = intradayCandles[exitID].open_ts

    return tradeToReturn

# Check if stop is hit. If stop hit - set exit price and timestamp; otherwise - update stop 
def updateTrade(trade, chartDict, session, strategy):
    trade['daysOpen'] = trade['daysOpen'] + 1
    trade['stop'] = strategy.getStop(chartDict, trade)
    # Find time when stop hit, also check if we gapped stop
    if  ((trade['direction'] == util.TickerStatus.LONG and chartDict['d'][-1].low <= trade['stop']) or
        (trade['direction'] == util.TickerStatus.SHORT and chartDict['d'][-1].high >= trade['stop'])):
        tradeDay = mtm.getCandleOpenCloseTime(chartDict['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
        intradayCandles = alpaca_chart.getChart(session, trade['symbol'], 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
        # Find intraday candle when stop is hit
        if trade['direction'] == util.TickerStatus.LONG:    # Bullish
            if intradayCandles[0].open < trade['stop']: # check if we gapped the stop
                entryID = -1
            else:
                entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.low > trade['stop']), None)
        else:   # Bearish
            if intradayCandles[0].open > trade['stop']: # check if we gapped the stop
                entryID = -1
            else:
                entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high < trade['stop']), None)
        # Record exit price and time
        if entryID is None:
            print(f'No exit found intraday but expected an exit based on daily chart on {tradeDay[0]}')
            trade['exitPrice'] = trade['stop']
        elif entryID == -1: # stop gapped
            trade['exitPrice'] = intradayCandles[0].open
            trade['exitTimestamp_sec'] = intradayCandles[0].open_ts        
        else:   # stop hit, record exit price and time (no need to check for gap - already checked earlier)
            trade['exitPrice'] = trade['stop']
            trade['exitTimestamp_sec'] = intradayCandles[entryID].open_ts

def printTrade(trade):
    entryTime = datetime.fromtimestamp(trade['entryTimestamp_sec'])
    gain_pct = 0
    if trade['exitTimestamp_sec'] == -1:
        exitTime = 'NA'
    else:
        exitTime = datetime.fromtimestamp(trade['exitTimestamp_sec'])
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
        chartDict['w'].append(copy.deepcopy(dayCandleToAdd))
        chartDict['w'][-1].previous_high = chartDict['w'][-2].high
        chartDict['w'][-1].previous_low = chartDict['w'][-2].low
    else:
        chartDict['w'][-1].high = max(chartDict['w'][-1].high, dayCandleToAdd.high)
        chartDict['w'][-1].low = min(chartDict['w'][-1].low, dayCandleToAdd.low)
        chartDict['w'][-1].close = dayCandleToAdd.close

    # Monthly flip
    if m != last_m:
        chartDict['m'].append(copy.deepcopy(dayCandleToAdd))
        chartDict['m'][-1].previous_high = chartDict['m'][-2].high
        chartDict['m'][-1].previous_low = chartDict['m'][-2].low
    else:
        chartDict['m'][-1].high = max(chartDict['m'][-1].high, dayCandleToAdd.high)
        chartDict['m'][-1].low = min(chartDict['m'][-1].low, dayCandleToAdd.low)
        chartDict['m'][-1].close = dayCandleToAdd.close

    # Quarterly flip
    if q != last_q:
        chartDict['q'].append(copy.deepcopy(dayCandleToAdd))
        chartDict['q'][-1].previous_high = chartDict['q'][-2].high
        chartDict['q'][-1].previous_low = chartDict['q'][-2].low
    else:
        chartDict['q'][-1].high = max(chartDict['q'][-1].high, dayCandleToAdd.high)
        chartDict['q'][-1].low = min(chartDict['q'][-1].low, dayCandleToAdd.low)
        chartDict['q'][-1].close = dayCandleToAdd.close

    # Yearly flip
    if y != last_y:
        chartDict['y'].append(copy.deepcopy(dayCandleToAdd))
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
    startDay_str = "2025-01-01 6:30:00"
    endDay_str = "2025-02-28 6:30:00"
    timezone = 'America/Los_Angeles'
    symbol = "SPY"

    #TDSession = session.initTDSession()
    trades = []
    session = alpaca_chart.initSession()
    strategy = bts("SimpleDailyAS")

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
        for trade in trades:
            if trade['exitPrice'] == - 1:
                updateTrade(trade, chartDict, session, strategy)

        # Check for new trades
        # Strategy is implemented in enterTrade function
        newTrade = enterTrade(symbol, chartDict, session, strategy)
        if bool(newTrade):
            trades.append(newTrade)

            
    # Log resulting trades
    for trade in trades:
        printTrade(trade)








