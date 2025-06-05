from datetime import datetime
from alpaca_chart import DataRetrieval
import util
import pandas as pd
import MarketTimeManager as mtm
import os
import copy
from BackTestStrategy import BackTestStrategy as bts
import multiprocessing as mp
from functools import partial
from earnings_calendar import EarningsCalendar
import time

# TODO: This may or may be needed. Commenting out for now
#def isAS(candle1, candle2, direction):
#    return (direction == util.TickerStatus.LONG and candle1['high'] > candle2['high']) or \
#    (direction == util.TickerStatus.SHORT and candle1['low'] < candle2['low'])

# Function to enter a trade based on the trigger defined by strategy. 
# Params:
#   sym - symbol to enter trade for
#   chartDictNew - dictionary with new chart data (including this day candle which may trigger a trade)
#   chartDictOld - dictionary with old chart data (up to and including previous day candle)
#   session - session object to retrieve data (if trade is triggered - pull 1min data to idenfiy entry time)
#   strategy - strategy object to use for entering trades
# Returns: dictionary with trade details with the keys:
#   'symbol' - ticker symbol
#   'entryPrice' - price at which trade is entered
#   'entryTimestamp_sec' - timestamp of entry in seconds (seconds since epoch), 
#   'entry_comment' - comment on the entry (e.g. which pattern is formed at all timeframes) #TODO: consider splitting into multiple keys for each timeframe
#   'direction' - direction of the trade (util.TickerStatus.LONG or util.TickerStatus.SHORT)
#   'exitPrice' - price at which trade is exited (if not exited - -1). This is populated if trade is stopped out the same day
#   'exitTimestamp_sec' - timestamp of exit in seconds (seconds since epoch), -1 if not stopped out
#   'daysOpen' - number of days trade is open (0 if not entered)
#   'stop_type' - type of stop (e.g. "stop hit", "stop gapped", "stop same day")
# If no trade is entered - returns None
def enterTrade(sym, chartDictNew, chartDictOld, session, strategy):
    tradeToReturn = []
    exitPrice = -1
    exitTimestamp = -1
    daysOpen = 0

    triggerPrice, direction, entry_comment = strategy.getNewTrade(chartDictNew, chartDictOld)
    if direction is None:
        return None
    elif direction == util.TickerStatus.LONG:   #TODO: get rid of entryLbl by printing .name of direction
        entryLbl = "LONG"
    else:
        entryLbl = "SHORT"
    
    # Find the exact time of entry
    tradeDay = session.market_time_manager.getCandleOpenCloseTime(chartDictNew['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
    intradayCandles = session.getChart([sym], 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
    intradayCandles = intradayCandles[sym]
    if direction == util.TickerStatus.LONG:
        entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high > triggerPrice), None)
    else:
        entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.low < triggerPrice), None)
    if entryID is None:
        print(f'{sym}: No entry found intraday but expected a {entryLbl} entry based on daily chart on {tradeDay[0]}, trigger = {triggerPrice}')
        return None
    else:   # record time of entry
        entryTimestamp = intradayCandles[entryID].open_ts

    tradeToReturn = {'symbol': sym, 
                     'entryPrice': triggerPrice, 'entryTimestamp_sec': entryTimestamp, 'entry_comment': entry_comment,
                     'daysOpen': daysOpen, 'direction': direction,
                     'exitPrice': exitPrice, 'exitTimestamp_sec': exitTimestamp, 
                    }
    # Get stop on the day of entry
    stopPrice, exit_comment = strategy.getStop(chartDictNew, chartDictOld, tradeToReturn)
    tradeToReturn['stop'] = stopPrice
    tradeToReturn['exit_comment'] = exit_comment
    # Check if stop out the same day (for efficiency, so we don't pull the same 1min data from API again)
    if direction == util.TickerStatus.LONG:
        exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if candle.low <= stopPrice), None)
    else:
        exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if candle.high >= stopPrice), None)
    if not exitID is None:
        tradeToReturn['exitPrice'] = stopPrice
        tradeToReturn['exitTimestamp_sec'] = intradayCandles[exitID].open_ts
        tradeToReturn['stop type'] = "stop same day"

    return tradeToReturn

# Update stop given the most recent chart. Check if stop is hit. If stop hit - set exit price and timestamp.
# This sequence (compute stop, and then check if it is hit) gives more flexibility than just using chart up to previous day, e.g. if we want to use current day open as a stop
# Params:
#   trade - dictionary with trade details
#   chartDictNew - dictionary with new chart data (including this day candle which may trigger a stop)
#   chartDictOld - dictionary with old chart data (up to and including previous day candle)
#   session - session object to retrieve data (if stop is hit - pull 1min data to idenfiy exit time)
#   strategy - strategy object to use for determining the stop
# Returns: None, updates trade dictionary in place
def updateTrade(trade, chartDictNew, chartDictOld, session, strategy):
    trade['daysOpen'] = trade['daysOpen'] + 1
    stopVal, exit_comment = strategy.getStop(chartDictNew, chartDictOld, trade)
    trade['stop'] = stopVal
    trade['exit_comment'] = exit_comment
    # If stop hit - find time when stop hit, also check if we gapped stop
    if  ((trade['direction'] == util.TickerStatus.LONG and chartDictNew['d'][-1].low <= trade['stop']) or
        (trade['direction'] == util.TickerStatus.SHORT and chartDictNew['d'][-1].high >= trade['stop'])):
        tradeDay = session.market_time_manager.getCandleOpenCloseTime(chartDictNew['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
        intradayCandles = session.getChart([trade['symbol']], 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
        intradayCandles = intradayCandles[trade['symbol']]
        # Find intraday candle when stop is hit
        if trade['direction'] == util.TickerStatus.LONG:    # Bullish
            if intradayCandles[0].open < trade['stop']: # check if we gapped the stop
                entryID = -1
            else:
                entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.low <= trade['stop']), None)
        else:   # Bearish
            if intradayCandles[0].open > trade['stop']: # check if we gapped the stop
                entryID = -1
            else:
                entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high >= trade['stop']), None)
        # Record exit price and time 
        if entryID is None:
            print(f'{trade['symbol']}: No {trade['direction']} exit found intraday but expected an exit based on daily chart on {tradeDay[0]}, stop = {trade['stop']}')
            trade['exitPrice'] = trade['stop']
            trade['stop type'] = "stop near-hit"
        elif entryID == -1: # stop gapped
            trade['exitPrice'] = intradayCandles[0].open
            trade['exitTimestamp_sec'] = intradayCandles[0].open_ts
            trade['stop type'] = "stop gapped"
        else:   # stop hit, record exit price and time (no need to check for gap - already checked earlier)
            trade['exitPrice'] = trade['stop']
            trade['exitTimestamp_sec'] = intradayCandles[entryID].open_ts
            trade['stop type'] = "stop hit"
  
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

def printChart(chart, filename):
    with open(filename, 'a') as f:
        for symbol in chart.keys():
            f.write(f"==========={symbol}=============\n")
            printChartSingleSymbol(chart[symbol], f)
            f.write("\n")
            
def printChartSingleSymbol(chartSingleSymbol, fileObject):
    for tf in chartSingleSymbol.keys():
        fileObject.write(f"Timeframe: {tf}\n")
        for candle in chartSingleSymbol[tf]:
            fileObject.write(candle.to_string_full() + '\n')
def printTradeDict(tradesDict, filename):
    if os.path.exists(filename):
        os.remove(filename)
    tradesList = []
    # Create a new file and write the header
    for subset in tradesDict.values():
        tradesList.extend(subset)
    tradesList = pd.DataFrame(tradesList)
    tradesList['exitPrice'] = tradesList['exitPrice'].replace(-1, None)
    tradesList['exitTimestamp_sec'] = tradesList['exitTimestamp_sec'].replace(-1, None)
    tradesList['gain %'] = tradesList['gain %'].replace(-1, None)
    tradesList['entryTimestamp_sec'] = pd.to_datetime(tradesList['entryTimestamp_sec'], unit='s').dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    tradesList['exitTimestamp_sec'] = pd.to_datetime(tradesList['exitTimestamp_sec'], unit='s').dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    tradesList['entryPrice'] = tradesList['entryPrice'].astype(float)
    tradesList['exitPrice'] = tradesList['exitPrice'].astype(float)
    tradesList['stop'] = tradesList['stop'].astype(float)
    tradesList['gain %'] = tradesList['gain %'].astype(float)
    tradesList['daysOpen'] = tradesList['daysOpen'].astype(int)
    tradesList['direction'] = tradesList['direction'].apply(lambda x: x.name)
    tradesList['symbol'] = tradesList['symbol'].astype(str)
    tradesList.to_csv(filename, index=False)
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

def backtest_symbol(dailyChart, chartDict, symbol, er_list, session, strategy):
    trades = []
    lastDay = pd.to_datetime(dailyChart[0].open_ts, unit='s')
    for day_id in range(1, len(dailyChart)):
        # Update charts
        dayCandleToAdd = dailyChart[day_id]
        dayDateToAdd = pd.to_datetime(dayCandleToAdd.open_ts, unit='s')
        chartDictNew = addDailyCandleToChart(chartDict, lastDay, dayCandleToAdd, dayDateToAdd)
        lastDay = dayDateToAdd
        #with open('chart.txt', 'a') as f:
        #    f.write(f"==========={symbol}=============\n")
        #    printChartSingleSymbol(chartDict, f)

        # Update trades
        for trade in trades:
            if trade['exitPrice'] == - 1:
                updateTrade(trade, chartDictNew, chartDict, session, strategy)

        # Check for new trades
        # Strategy is implemented in enterTrade function
        newTrade = enterTrade(symbol, chartDictNew, chartDict, session, strategy)
        if bool(newTrade):
            trades.append(newTrade)
        
        # Check for potential ER
        if pd.to_datetime(chartDictNew['d'][-1].open_ts, unit='s', utc=True).date() in er_list:
            for trade in trades:
                if trade['exitPrice'] == - 1:
                    strategy.handleER(trade, chartDictNew)
        
        chartDict = copy.deepcopy(chartDictNew)  # Update chartDict to the new one with the latest daily candle
    # Log resulting trades
    #for trade in trades:
    #    printTrade(trade)
    return trades 

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
    startDay_str = "2025-01-01 0:30:00"
    endDay_str = "2025-04-30 23:30:00"
    timezone = 'America/Los_Angeles'
    earnings_file = '/Users/ilyatoytman/Git/stratBot/EarningsCalendar_2025-05-18.csv'
    watchlist_name = 'NASDAQ100_2025'
    #watchlist_name = 'test_wl'
    watchlist = pd.read_csv('Watchlists/' + watchlist_name + '.csv', header = None)
    #watchlist = pd.read_csv('Watchlists/test_wl.csv', header = None)
    watchlist = watchlist[0].to_list()
    strategy_name = "HammerShooterInsideDayAS"
    test_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    tradeLogFileName = "./Trades/trades_" + startDay_str.split(' ')[0].replace('-', '') + "_" + endDay_str.split(' ')[0].replace('-', '') + "_" + watchlist_name + "_" + strategy_name + "_" + test_timestamp + ".csv"
    os.makedirs('./Trades/', exist_ok=True)
    #TDSession = session.initTDSession()
    trades = []
    #mgr = mp.Manager()
    mtm = mtm.MarketTimeManager()
    session = DataRetrieval(market_time_manager=mtm)
    strategy = bts(strategy_name)
    er = EarningsCalendar(earnings_file)
    
    # Currently testing only Daily and higher TF strategy, so we simply truncate startDay to the beginning of the day and endDay to the end of the day
    startDay = pd.to_datetime(startDay_str).tz_localize(timezone).replace(hour=6, minute=30, second=0)
    endDay = pd.to_datetime(endDay_str).tz_localize(timezone).replace(hour=23, minute=59, second=0)
    # Since our actionable signals require previous day to be bullish/bearish, we need to get the last day when market was open prior to startDay
    startDayToQuery = mtm.getCandleOpenCloseTime(startDay.timestamp(), 'd', n_pre=1, n_post=0)
    lastDayBeforeRange = startDayToQuery['pre'][0]
    
    # Get daily chart spanning full range of days. This is dictionary {'symbol' --> [candle list]}
    dailyChart = session.getChart(symbol_list=watchlist, timeframe_sym='d', start_timestamp=lastDayBeforeRange[0].timestamp(), end_timestamp=endDay.timestamp())
    # Note: API calls can get multiple symbols at once, but not multiple timeframes for the same symbol. So we need to get all timeframes for each symbol separately
    TF_sym_list = ['d', 'w', 'm', 'q', 'y']
    chartByTimeframe = dict.fromkeys(TF_sym_list)
    # Init daily chart (do it separately to save on extra query to Alpaca API). This creates a dictionary {'timeframe = d' --> {'symbol' --> first daily candle}}
    chartByTimeframe['d'] = {symbol: [dailyChart[symbol][0]] for symbol in dailyChart.keys() if symbol} # extra square brackets are needed to make a list containing a single candle
    # Initialize all higher TF charts (W and higher). This will generate a dictionary {'timeframe' --> {'symbol' --> [candle list]}}
    # Note: we need an extra candle for each TF to evaluate if there is AS on that TF
    for TF_sym in TF_sym_list[1:]:
        firstCandleToQuery = mtm.getCandleOpenCloseTime(startDay.timestamp(), TF_sym, n_pre=1, n_post=0)
        firstCandleToQuery = firstCandleToQuery['pre'][0]
        chartByTimeframe[TF_sym] = session.getChart(symbol_list=watchlist, timeframe_sym=TF_sym, start_timestamp=firstCandleToQuery[0].timestamp(), end_timestamp=lastDayBeforeRange[1].timestamp())
    # Swap order of keys in the dictionary to {'symbol' --> {'timeframe' --> [candle list]}}
    chartDict = {symbol: {TF_sym: chartByTimeframe[TF_sym][symbol] for TF_sym in chartByTimeframe.keys()} for symbol in watchlist}
        
    #lastDay = startDayToQuery[0]
    if os.path.exists('chart.txt'):
        os.remove('chart.txt')
    #printChart(chartDict, 'chart.txt')
    
    symbol_valid = set(dailyChart.keys()) & set(chartDict.keys())
    symbol_invalid = set(dailyChart.keys()) ^ set(chartDict.keys())
    if symbol_invalid:
        print(f"Symbols in daily chart and higher timeframe charts do not match and will be ignored: {symbol_invalid}")
    dailyChart_candles = [dailyChart[symbol] for symbol in symbol_valid]
    chartDict_candles = [chartDict[symbol] for symbol in symbol_valid]
    er_per_symbol = [er.get_ER_by_ticker(symbol) for symbol in symbol_valid]
    # Start backtesting for each symbol in parallel
    start_time = time.perf_counter()
    with mp.Pool() as pool:
        total_result = pool.starmap(partial(backtest_symbol, session=session, strategy=strategy), zip(dailyChart_candles, chartDict_candles, symbol_valid, er_per_symbol))
    end_time = time.perf_counter()
    print(f"Backtesting completed in {end_time - start_time:.2f} seconds")
    all_trades = {}
    gain_summary = {}
    for sublist in total_result:
        #pd.DataFrame(sublist).to_csv('trades.csv', mode='a', index=False)
        for trade in sublist:
            if trade['exitPrice'] == -1:
                gain = 0
                trade['gain %'] = None
            else:
                if (trade['direction'] == util.TickerStatus.LONG):
                    trade['gain %'] = 100*(trade['exitPrice']/trade['entryPrice']-1)
                else:
                    trade['gain %'] = 100*(1- trade['exitPrice']/trade['entryPrice'])
                gain = trade['gain %']

            if trade['symbol'] in all_trades:
                all_trades[trade['symbol']].append(trade)
                gain_summary[trade['symbol']] += gain
            else:
                all_trades[trade['symbol']] = [trade]
                gain_summary[trade['symbol']] = gain
    gain_summary = pd.DataFrame(gain_summary.items(), columns=['symbol', 'gain %'])
    print('Backtesting summary:')
    print('====================')
    print(f'Time span: {startDay} to {endDay}')
    print('Strategy: ' + strategy_name)
    print('Total gain = {:.2f}%'.format(gain_summary['gain %'].sum()))
    print('Watchlist: ' + watchlist_name)
    #print('Symbols: ' + str(watchlist))
    #print(gain_summary)
    print()
    printTradeDict(all_trades, tradeLogFileName)
    print(f'Trade details logged in {tradeLogFileName}')
    print('====================')

   







