from datetime import datetime
from alpaca_chart import DataRetrieval, SharedRateLimiter
import util
import pandas as pd
import MarketTimeManager
import os
import copy
from BackTestStrategy import BackTestStrategy as bts
import multiprocessing as mp
from functools import partial
from earnings_calendar import EarningsCalendar
import time
import candles
import log_functions
import logging

shared_limiter = None  # Global variable to hold the shared rate limiter instance
logger = logging.getLogger(__name__)

def init_pool(limiter, log_queue):
    global shared_limiter
    shared_limiter = limiter  # Assign the shared rate limiter to the global variable
    log_functions.subprocess_init(log_queue)

# TODO: This may or may be needed. Commenting out for now
#def isAS(candle1, candle2, direction):
#    return (direction == util.TickerStatus.LONG and candle1['high'] > candle2['high']) or \
#    (direction == util.TickerStatus.SHORT and candle1['low'] < candle2['low'])

# Function to enter a trade based on the trigger defined by strategy. To minimize the number of API calls, the analysis is done in two steps:
#   1. Screen for possible trade based on Daily+HTF charts (implemented by strategy)
#   2. If potential trade - pull intraday chart data to confirm trade and if confirmed - populate trade details. Trade confirmation and details are implemented by strategy.
# Params:
#   sym - symbol to enter trade for
#   chartDictNew - dictionary with new chart data (including this day candle which may trigger a trade)
#   chartDictOld - dictionary with old chart data (up to and including previous day candle)
#   session - session object to retrieve data (if trade is triggered - pull 1min data to idenfiy entry time)
#   strategy - strategy object to use for entering trades
# Returns: list of dictionaries with trade details with the keys:
#   'symbol' - ticker symbol
#   'entryPrice' - price at which trade is entered
#   'entryTimestamp_sec' - timestamp of entry in seconds (seconds since epoch), 
#   'entry_comment' - comment on the entry (e.g. which pattern is formed at all timeframes) #TODO: consider splitting into multiple keys for each timeframe
#   'direction' - direction of the trade (util.TickerStatus.LONG or util.TickerStatus.SHORT)
#   'exitPrice' - price at which trade is exited (if not exited - -1). This is populated if trade is stopped out the same day
#   'exitTimestamp_sec' - timestamp of exit in seconds (seconds since epoch), -1 if not stopped out
#   'daysOpen' - number of days trade is open (0 if not entered)
#   'stop_type' - type of stop (e.g. "stop hit", "stop gapped", "stop same day")
# If no trade is entered - returns empty list
def enterTrade(sym, chartDictNew, chartDictOld, session, strategy):
    tradeToReturn = []
    exitPrice = -1
    exitTimestamp = -1
    daysOpen = 0
    # Screen daily+HTF charts for entry. This returns a list of tuples, each tuple is (triggerPrice, direction) - maybe 1 or 2 entries (if both long and short entries are possible)
    # This is done to minimize the number of API calls, so we don't pull intraday chart unless we have a potential trade
    # If no potential trade - return empty list
    potentialTrade = strategy.screenTrade(chartDictNew, chartDictOld)
    if potentialTrade is False:
        return tradeToReturn
    #elif direction == util.TickerStatus.LONG:   #TODO: get rid of entryLbl by printing .name of direction
    #    entryLbl = "LONG"
    #else:
    #    entryLbl = "SHORT"

    # Get intraday chart and find the exact time of entry. Note: there could be several trades in different directions on the same day, so we need to return a list of trades
    tradeDay = session.market_time_manager.getCandleOpenCloseTime(chartDictNew['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
    intradayCandles = session.getChart([sym], 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
    intradayCandles = intradayCandles[sym]
    firstCandleID = 0
    tradeDetailList = strategy.getNewTrade(chartDictNew, chartDictOld, intradayCandles, firstCandleID)
    for trade in tradeDetailList:
        triggerPrice = trade[0]
        direction = trade[1]
        if len(trade) > 2:
            targetPrice = trade[2]
        elif direction == util.TickerStatus.LONG:
            targetPrice = float('inf')
        elif direction == util.TickerStatus.SHORT:
            targetPrice = 0.0
        if direction == util.TickerStatus.LONG:
            entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.high > triggerPrice), None)
        else:
            entryID = next((ii for ii, candle in enumerate(intradayCandles) if candle.low < triggerPrice), None)
        if entryID is None:
            logger.warning(f'{sym}: No entry found intraday but expected a {direction.name} entry based on daily chart on {tradeDay[0]}, trigger = {triggerPrice}')
            continue
        entryTimestamp = intradayCandles[entryID].open_ts
        currentTrade = ({'symbol': sym, 
                         'entryPrice': triggerPrice, 'entryTimestamp_sec': entryTimestamp,
                         'daysOpen': daysOpen, 'direction': direction,
                         'exitPrice': exitPrice, 'exitTimestamp_sec': exitTimestamp,
                         'stop type': '', 'target': targetPrice
                        })
 
        # Record combos and TFC during entry 
        # Setup entryPrice to be just above/below trigger price to avoid always reporting inside day
        if direction == util.TickerStatus.LONG:
            entryPrice = triggerPrice + 0.01
        else:
            entryPrice = triggerPrice - 0.01
        currentDayLow = min(candle.low for candle in intradayCandles[:entryID+1])
        currentDayHigh = max(candle.high for candle in intradayCandles[:entryID+1])
        # Create a dictionary with current partial candle (just at the entry) for each timeframe
        currentCandleDict = dict.fromkeys(chartDictNew.keys())
        for tf in chartDictOld.keys():    
            # Check if this day falls into the new HTF candle (ie we don't have decoupling yet)
            if chartDictOld[tf][-1].open_ts < chartDictNew[tf][-1].open_ts:
                currentCandleDict[tf] = candles.Candle(
                    timestamp=chartDictNew[tf][-1].open_ts,
                    open=chartDictNew[tf][-1].open,
                    high=currentDayHigh,
                    low=currentDayLow,
                    close=entryPrice,
                    prev_high=chartDictOld[tf][-1].high,
                    prev_low=chartDictOld[tf][-1].low
                )
            else: # we have decoupling, this partial daily candle needs to be aggregated into HTF candle
                currentCandleDict[tf] = candles.Candle(
                    timestamp=chartDictNew[tf][-1].open_ts,
                    open=chartDictNew[tf][-1].open,
                    high=max(currentDayHigh, chartDictOld[tf][-1].high),
                    low=min(currentDayLow, chartDictOld[tf][-1].low),
                    close=entryPrice,
                    prev_high=chartDictOld[tf][-1].previous_high,
                    prev_low=chartDictOld[tf][-1].previous_low
                )
            # Record candle combo 
            if len(chartDictNew[tf]) < 3:
                logger.warning(f"Warning: Not enough candles in {tf} timeframe to record combo for {sym} on {tradeDay[0]}. Reduced combo recording.")
                currentTrade[tf] = chartDictNew[tf][-2].to_string() + "-" + currentCandleDict[tf].to_string()
                currentTrade[tf + " combo"] = (chartDictNew[tf][-2].get_kind() + chartDictNew[tf][-2].get_subtype() + "-" + 
                                               currentCandleDict[tf].get_kind() + currentCandleDict[tf].get_subtype())
            else:
                currentTrade[tf] = chartDictNew[tf][-3].to_string() + "-" + chartDictNew[tf][-2].to_string() + "-" + currentCandleDict[tf].to_string()   
                currentTrade[tf + " combo"] = (chartDictNew[tf][-3].get_kind() + chartDictNew[tf][-3].get_subtype() + "-" + 
                                           chartDictNew[tf][-2].get_kind() + chartDictNew[tf][-2].get_subtype() + "-" + 
                                           currentCandleDict[tf].get_kind() + currentCandleDict[tf].get_subtype())
                
            currentTrade["Prev D pattern"] = chartDictNew['d'][-2].get_pattern()
            # Record TFC
            if entryPrice > chartDictNew[tf][-1].open:
                currentTrade["TFC " + tf] = "G"
            else:
                currentTrade["TFC " + tf] = "R"
        
        # Check for same day stop out
        # Get stop on the day of entry
        stopPrice, exit_comment, *targetPrice = strategy.getStop(chartDictNew, chartDictOld, currentTrade, intradayCandles, entryID)
        currentTrade['stop'] = stopPrice
        currentTrade['initial stop'] = stopPrice  # Initial stop is the same as the stop on the day of entry
        currentTrade['RR'] = (currentTrade['target'] - currentTrade['entryPrice']) / (currentTrade['entryPrice'] - currentTrade['stop']) 
        currentTrade['exit_comment'] = exit_comment
        if targetPrice:
            currentTrade['target'] = targetPrice[0]  # in case target is changed every day, and not just set at entry
        # Check if stop out the same day (for efficiency, so we don't pull the same 1min data from API again)
        if direction == util.TickerStatus.LONG:
            exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if (candle.low <= stopPrice or candle.high >= currentTrade['target'])), None)
            if not exitID is None:
                if intradayCandles[exitID].low <= stopPrice:
                    currentTrade['stop type'] = "same day stop hit"
                    currentTrade['exitPrice'] = currentTrade['stop']
                elif intradayCandles[exitID].high >= currentTrade['target']:
                    currentTrade['stop type'] = "same day target hit"
                    currentTrade['exitPrice'] = currentTrade['target']
        else:
            exitID = next((ii for ii, candle in enumerate(intradayCandles[entryID+1:], start=entryID+1) if (candle.high >= stopPrice or candle.low <= currentTrade['target'])), None)
            if not exitID is None:
                if intradayCandles[exitID].high >= stopPrice:
                    currentTrade['stop type'] = "same day stop hit"
                    currentTrade['exitPrice'] = currentTrade['stop']
                elif intradayCandles[exitID].low <= currentTrade['target']:
                    currentTrade['stop type'] = "same day target hit"
                    currentTrade['exitPrice'] = currentTrade['target']
        currentTrade['initialStop'] = currentTrade['stop']
        currentTrade["RR"] = (currentTrade['target']-currentTrade['entryPrice'])/(currentTrade['entryPrice'] - currentTrade['stop'])
        if not exitID is None:
            currentTrade['exitTimestamp_sec'] = intradayCandles[exitID].open_ts
        tradeToReturn.append(currentTrade)
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
    stopVal, exit_comment, *targetVal = strategy.getStop(chartDictNew, chartDictOld, trade)
    if targetVal:
        trade['target'] = targetVal[0]  # in case target is changed every day, and not just set at entry

    trade['stop'] = stopVal
    trade['exit_comment'] = exit_comment
    # If stop hit or target achieved - find time when stop hit, also check if we gapped stop or target
    if  ((trade['direction'] == util.TickerStatus.LONG and (chartDictNew['d'][-1].low <= trade['stop'] or chartDictNew['d'][-1].high >= trade['target'])) or
        (trade['direction'] == util.TickerStatus.SHORT and (chartDictNew['d'][-1].high >= trade['stop'] or chartDictNew['d'][-1].low <= trade['target']))):
        tradeDay = session.market_time_manager.getCandleOpenCloseTime(chartDictNew['d'][-1].open_ts, 'd', n_pre=0, n_post=0)['current']
        intradayCandles = session.getChart([trade['symbol']], 'm1', tradeDay[0].timestamp(), tradeDay[1].timestamp())
        intradayCandles = intradayCandles[trade['symbol']]
        # Find intraday candle when stop is hit
        if trade['direction'] == util.TickerStatus.LONG:    # Bullish
            if intradayCandles[0].open < trade['stop']: # check if we gapped the stop
                entryID = -1
            elif intradayCandles[0].open > trade['target']:
                entryID = -2
            else:
                entryID = next((ii for ii, candle in enumerate(intradayCandles) if (candle.low <= trade['stop'] or candle.high >= trade['target'])), None)
                if entryID is None:
                    logger.warning(f'{trade['symbol']}: No {trade['direction'].name} exit found intraday but expected an exit based on daily chart on {tradeDay[0]}, stop = {trade['stop']}, target = {trade['target']}. Keep trade open')
                    return
                if intradayCandles[entryID].low <= trade['stop']:
                    trade['stop type'] = "stop hit"
                    trade['exitPrice'] = trade['stop']
                elif intradayCandles[entryID].high >= trade['target']:
                    trade['stop type'] = "target hit"
                    trade['exitPrice'] = trade['target']
        else:   # Bearish
            if intradayCandles[0].open > trade['stop']: # check if we gapped the stop
                entryID = -1
            elif intradayCandles[0].open < trade['target']:
                entryID = -2
            else:
                entryID = next((ii for ii, candle in enumerate(intradayCandles) if (candle.high >= trade['stop'] or candle.low <= trade['target'])), None)
                if entryID is None:
                    logger.warning(f'{trade['symbol']}: No {trade['direction'].name} exit found intraday but expected an exit based on daily chart on {tradeDay[0]}, stop = {trade['stop']}, target = {trade['target']}. Keep trade open')
                    return
                if intradayCandles[entryID].high >= trade['stop']:
                    trade['stop type'] = "stop hit"
                    trade['exitPrice'] = trade['stop']
                elif intradayCandles[entryID].low <= trade['target']:
                    trade['stop type'] = "target hit"
                    trade['exitPrice'] = trade['target']
        # Record exit price and time 
        if entryID < 0: # stop or target gapped 
            trade['exitPrice'] = intradayCandles[0].open
            trade['stop type'] = "stop gapped" if entryID == -1 else "target gapped"
            trade['exitTimestamp_sec'] = intradayCandles[0].open_ts
        else:   # stop hit or target reached, price is already recorded earlier, just record the time (no need to check for gap - already checked earlier)
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
    chartDictNew = copy.deepcopy(chartDict)
    w = dayDateToAdd.week
    m = dayDateToAdd.month
    q = (m-1)//3
    y = dayDateToAdd.year
    last_w = lastDayDate.week
    last_m = lastDayDate.month
    last_q = (last_m-1)//3
    last_y = lastDayDate.year
    chartDictNew['d'].append(dayCandleToAdd)
    # Weekly flip
    if w != last_w:
        chartDictNew['w'].append(copy.deepcopy(dayCandleToAdd))
        chartDictNew['w'][-1].previous_high = chartDict['w'][-1].high
        chartDictNew['w'][-1].previous_low = chartDict['w'][-1].low
    else:
        chartDictNew['w'][-1].high = max(chartDict['w'][-1].high, dayCandleToAdd.high)
        chartDictNew['w'][-1].low = min(chartDict['w'][-1].low, dayCandleToAdd.low)
        chartDictNew['w'][-1].close = dayCandleToAdd.close

    # Monthly flip
    if m != last_m:
        chartDictNew['m'].append(copy.deepcopy(dayCandleToAdd))
        chartDictNew['m'][-1].previous_high = chartDict['m'][-1].high
        chartDictNew['m'][-1].previous_low = chartDict['m'][-1].low
    else:
        chartDictNew['m'][-1].high = max(chartDict['m'][-1].high, dayCandleToAdd.high)
        chartDictNew['m'][-1].low = min(chartDict['m'][-1].low, dayCandleToAdd.low)
        chartDictNew['m'][-1].close = dayCandleToAdd.close

    # Quarterly flip
    if q != last_q:
        chartDictNew['q'].append(copy.deepcopy(dayCandleToAdd))
        chartDictNew['q'][-1].previous_high = chartDict['q'][-1].high
        chartDictNew['q'][-1].previous_low = chartDict['q'][-1].low
    else:
        chartDictNew['q'][-1].high = max(chartDict['q'][-1].high, dayCandleToAdd.high)
        chartDictNew['q'][-1].low = min(chartDict['q'][-1].low, dayCandleToAdd.low)
        chartDictNew['q'][-1].close = dayCandleToAdd.close

    # Yearly flip
    if y != last_y:
        chartDictNew['y'].append(copy.deepcopy(dayCandleToAdd))
        chartDictNew['y'][-1].previous_high = chartDict['y'][-1].high
        chartDictNew['y'][-1].previous_low = chartDict['y'][-1].low
    else:
        chartDictNew['y'][-1].high = max(chartDict['y'][-1].high, dayCandleToAdd.high)
        chartDictNew['y'][-1].low = min(chartDict['y'][-1].low, dayCandleToAdd.low)
        chartDictNew['y'][-1].close = dayCandleToAdd.close
    return chartDictNew

def backtest_symbol(dailyChart, chartDict, symbol, market_time_manager, er_list, strategy):    
    session = DataRetrieval(rate_limiter=shared_limiter, market_time_manager=market_time_manager)  # Recreate session to avoid issues with multiprocessing
    
    logger.info(f"Starting backtest for {symbol}")
    trades = []
    lastDay = pd.to_datetime(dailyChart[1].open_ts, unit='s')
    for day_id in range(2, len(dailyChart)):
        # Update charts
        dayCandleToAdd = dailyChart[day_id]
        dayDateToAdd = pd.to_datetime(dayCandleToAdd.open_ts, unit='s')
        logger.debug(f"{symbol}: Adding daily candle for {dayDateToAdd.date()}")
        chartDictNew = addDailyCandleToChart(chartDict, lastDay, dayCandleToAdd, dayDateToAdd)
        lastDay = dayDateToAdd

        # Update trades
        for trade in trades:
            if trade['exitPrice'] == - 1:
                updateTrade(trade, chartDictNew, chartDict, session, strategy)

        # Check for new trades
        # Strategy is implemented in enterTrade function. Note: enterTrade checks for same day stop out and updates trades accordingly
        newTradeList = enterTrade(symbol, chartDictNew, chartDict, session, strategy)
        if bool(newTradeList):
            #trades.append(newTrade)
            trades.extend(newTradeList)
        
        # Check for potential ER
        if pd.to_datetime(chartDictNew['d'][-1].open_ts, unit='s', utc=True).date() in er_list:
            for trade in trades:
                if trade['exitPrice'] == - 1:
                    strategy.handleER(trade, chartDictNew)
        
        chartDict = copy.deepcopy(chartDictNew)  # Update chartDict to the new one with the latest daily candle
    # Log resulting trades
    #for trade in trades:
    #    printTrade(trade)
    logger.info(f"Completed backtest for {symbol}")
    return trades 
    
# Function to run backtest for given watchlist and strategy between startDay and endDay
# startDay_str and endDay_str are strings in the format "YYYY-MM-DD HH:MM:SS" in PST timezone
def runBacktest(startDay_str, endDay_str, wl, strategy_name, earnings_file):
    timezone = 'America/Los_Angeles'
    watchlist = pd.read_csv('Watchlists/' + wl + '.csv', header = None)
    watchlist = watchlist[0].to_list()
    test_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    tradeLogFileName = "./Trades/trades_" + startDay_str.split(' ')[0].replace('-', '') + "_" + endDay_str.split(' ')[0].replace('-', '') + "_" + watchlist_name + "_" + strategy_name + "_" + test_timestamp + ".csv"
    os.makedirs('./Trades/', exist_ok=True)
    log_config = log_functions.log_init()
    log_queue, log_proc = log_functions.start_logging_process(log_config)
    #log_listener.start()
    
    logger.info(f"""Main process starting. Parameters: 
                range: {startDay_str} to {endDay_str}
                watchlist: {wl}
                strategy: {strategy_name}
                earnings file: {earnings_file}""")
    
    mtm = MarketTimeManager.MarketTimeManager()
    session = DataRetrieval(market_time_manager=mtm)
    strategy = bts(strategy_name)
    er = EarningsCalendar(earnings_file)


    # Currently testing only Daily and higher TF strategy, so we simply truncate startDay to the beginning of the day and endDay to the end of the day
    startDay = pd.to_datetime(startDay_str).tz_localize(timezone).replace(hour=6, minute=30, second=0)
    endDay = pd.to_datetime(endDay_str).tz_localize(timezone).replace(hour=23, minute=59, second=0)
    # Pull two extra days before startDay to be able to form combos like 3-2-2, 1-2-2 (for rev strat detection)
    startDayToQuery = mtm.getCandleOpenCloseTime(startDay.timestamp(), 'd', n_pre=2, n_post=0)
    lastDayBeforeRange = startDayToQuery['pre'][0]
    
    # Get daily chart spanning full range of days. This is dictionary {'symbol' --> [candle list]}
    dailyChart = session.getChart(symbol_list=watchlist, timeframe_sym='d', start_timestamp=startDayToQuery['pre'][-1][0].timestamp(), end_timestamp=endDay.timestamp())
    # Identify symbols that do not have candle at previous day before startDay (ie not enough data to form combos) - these will have to be queried separately
    symbols_missing_daily_candle = [symbol for symbol in dailyChart.keys() if dailyChart[symbol][0].open_ts > startDayToQuery['pre'][-1][0].timestamp()]
    symbol_complete_daily_candle = [symbol for symbol in dailyChart.keys() if dailyChart[symbol][0].open_ts <= startDayToQuery['pre'][-1][0].timestamp()]
    # Note: API calls can get multiple symbols at once, but not multiple timeframes for the same symbol. So we need to get all timeframes for each symbol separately
    TF_sym_list = ['d', 'w', 'm', 'q', 'y']
    chartByTimeframe = dict.fromkeys(TF_sym_list)
    # Init daily chart (do it separately to save on extra query to Alpaca API). Only for symbols that have daily candles starting from startDayToQuery['pre']
    # This creates a dictionary {'timeframe = d' --> {'symbol' --> first daily candle}}
    chartByTimeframe['d'] = {symbol: dailyChart[symbol][0:2] for symbol in watchlist if len(dailyChart[symbol])>1} # reminder: [0:2] gets first two candles (inclusive-exclusive range)
    # For symbols missing daily candle at previous day before startDay - we still keep 2 candles but need to adjust higher TF charts to request starting from timestamp of the first day in DailyChart?
    # Initialize all higher TF charts (W and higher). This will generate a dictionary {'timeframe' --> {'symbol' --> [candle list]}}
    # Note: we need an extra candle for each TF to evaluate if there is AS on that TF
    for TF_sym in TF_sym_list[1:]:
        firstCandleToQuery = mtm.getCandleOpenCloseTime(startDay.timestamp(), TF_sym, n_pre=2, n_post=0)
        firstCandleToQuery = firstCandleToQuery['pre'][-1]
        chartByTimeframe[TF_sym] = session.getChart(symbol_list=symbol_complete_daily_candle, timeframe_sym=TF_sym, start_timestamp=firstCandleToQuery[0].timestamp(), end_timestamp=lastDayBeforeRange[1].timestamp())
        # For symbols with daily candles starting at later time - first two candles are buffer (just like the regular complete ones), use the start of the third daily candle as startDay for higher TF
        for s in symbols_missing_daily_candle:
            if len(dailyChart[s]) < 3:
                logger.warning(f"Not enough daily candles for symbol {s} to form higher timeframe charts. Skipping this symbol.")
                continue
            firstDailyCandles = mtm.getCandleOpenCloseTime(dailyChart[s][2].open_ts, 'd', n_pre=1, n_post=0) # dailyChart[s][2] is the first day to backtest, its open time is startDay

            firstCandleToQuery = mtm.getCandleOpenCloseTime(firstDailyCandles['current'][0].timestamp(), TF_sym, n_pre=2, n_post=0) # beginning of two high TF candles prior to first day to backtest
            firstCandleToQuery = firstCandleToQuery['pre'][-1]
            lastDayBeforeBackTest = firstDailyCandles['pre'][0] # last day before backtest day for this symbol
            chart_single_symbol = session.getChart(symbol_list=[s], timeframe_sym=TF_sym, start_timestamp=firstCandleToQuery[0].timestamp(), end_timestamp=lastDayBeforeBackTest[1].timestamp())
            chartByTimeframe[TF_sym][s] = chart_single_symbol[s]
 
    # Swap order of keys in the dictionary to {'symbol' --> {'timeframe' --> [candle list]}}
    chartDict = {symbol: {TF_sym: chartByTimeframe[TF_sym][symbol] for TF_sym in chartByTimeframe.keys()} for symbol in chartByTimeframe[TF_sym].keys()}
    
    # This is for debugging purposes, print chart into a file
    #if os.path.exists('chart.txt'):
    #    os.remove('chart.txt')
    #printChart(chartDict, 'chart.txt')
    
    symbol_valid = set(dailyChart.keys()) & set(chartDict.keys())
    symbol_invalid = set(dailyChart.keys()) ^ set(chartDict.keys())
    if symbol_invalid:
        logger.warning(f"Symbols in daily chart and higher timeframe charts do not match and will be ignored: {symbol_invalid}")
    
    er_dict = {symbol: er.get_ER_by_ticker(symbol) for symbol in symbol_valid}
    # Start backtesting for each symbol in parallel
    start_time = time.perf_counter()
    with mp.Manager() as manager:
        limiter = SharedRateLimiter(manager)
        with mp.Pool(initializer=init_pool, initargs=(limiter, log_queue)) as pool: # remove number of processes from the call
            total_result = pool.starmap(backtest_symbol, 
                            [(dailyChart[symbol], chartDict[symbol], symbol, mtm, er_dict[symbol], strategy) for symbol in symbol_valid]
                        )  
    #with mp.Pool() as pool:
    #    total_result = pool.starmap(partial(backtest_symbol, session=session, strategy=strategy), zip(dailyChart_candles, chartDict_candles, symbol_valid, er_per_symbol))
    end_time = time.perf_counter()
    logger.info(f"Backtesting completed in {end_time - start_time:.2f} seconds")
    all_trades = {}
    gain_summary = {}
    for sublist in total_result:
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

    logger.info(f"""
    ========================
        Backtesting summary:
        Time span: {startDay} to {endDay}
        Strategy: {strategy_name}
        Watchlist: {wl}
        Total gain = {gain_summary['gain %'].sum():.2f}%
        Number of trades: {gain_summary.shape[0]}
        Trade details logged in {tradeLogFileName}
    ========================""")

    printTradeDict(all_trades, tradeLogFileName)
    print("Stopping log listener...")
    log_functions.stop_logging_process(log_queue, log_proc)
    print("Log listener stopped")
    # Move log file
    try:
    # Rename the file
        os.rename("strat_bot.log", "strat_bot_" + test_timestamp + ".log")
        print(f"Program log saved to 'strat_bot_{test_timestamp}.log'")
    except FileNotFoundError:
        print(f"Error: The file 'strat_bot.log' was not found.")
    except OSError as e:
        print(f"Error renaming file: {e}")
   
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
    startDay_str = "2023-01-01 0:30:00"
    endDay_str = "2025-12-20 23:30:00"
    timezone = 'America/Los_Angeles'
    earnings_file = '/Users/ilyatoytman/Git/stratBot/EarningsCalendar_2025-12-21.csv'
    watchlist_name = 'NASDAQ100_2025'
    strategy_name = "StratLab2dGM"
    runBacktest(
        startDay_str=startDay_str, 
        endDay_str=endDay_str, 
        wl=watchlist_name, 
        strategy_name=strategy_name, 
        earnings_file=earnings_file
    )
    







