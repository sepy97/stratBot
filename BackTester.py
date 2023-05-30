from datetime import datetime, timedelta
#import session
import alpaca_chart
import util

# TODO: ALL TIMESTAMPS ARE IN SECONDS, NOT MILLISECONDS - RESPECTIVE KEYS NEED TO BE UPDATED
# Assumes candle1 is candle at T-2, candle2 is candle at T-1
def isAS(candle1, candle2, direction):
    return (direction == util.TickerStatus.LONG and candle1['high'] > candle2['high']) or \
    (direction == util.TickerStatus.SHORT and candle1['low'] < candle2['low'])

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

# check if stop is hit. If stop hit - set exit price and timestamp; otherwise - update stop 
def updateTrade(trade, lastCandle, direction, session):
        if (direction == util.TickerStatus.LONG and lastCandle['low'] >= trade['stop']) or \
            (direction == util.TickerStatus.SHORT and lastCandle['high'] <= trade['stop']):   # daily candle never crossed stop
            trade['daysOpen'] = trade['daysOpen'] + 1
            trade['stop'] = getNewStop(trade, lastCandle, direction)

        else:   # find time when stop hit, also check if we gapped stop
            #lastCandleTime = datetime.fromtimestamp(lastCandle['datetime']/1000).replace(hour = 0) + timedelta(days = 1) # TD returns previous day 10pm as timestamp for daily candle
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



#TDSession = session.initTDSession()
session = alpaca_chart.initSession()

startDay = datetime.timestamp(datetime(2022, 2, 1, 6, 30, 0))
endDay = datetime.timestamp(datetime(2022, 3, 25, 6, 30, 0))
symbol = "SPY"
direction = util.TickerStatus.SHORT
trades = []
#data = TDSession.get_price_history(symbol=symbol, start_date=startDay.timestamp()*1000, end_date=endDay.timestamp()*1000, frequency_type="daily", frequency=1, extended_hours=False)
#data = TDSession.get_price_history(symbol=symbol, period_type="month", period=None, start_date=int(startDay.timestamp()*1000), end_date=int(endDay.timestamp()*1000), frequency_type="daily", frequency=1, extended_hours=False)
#data = TDSession.get_price_history(symbol=symbol, period_type="month", period=1, frequency_type="daily", frequency=1, extended_hours=False)
#candles = data["candles"] 
candles = alpaca_chart.getChart(session, symbol, 'd', startDay, endDay)

for ii in range(2, len(candles)):
    for trade in trades:
        if trade['exitPrice'] == - 1: # trade still active
            updateTrade(trade, candles[ii], direction, session)
    if isAS(candles[ii-2], candles[ii-1], direction):
        #try to enter: check for trigger and ensure no gap over trigger
        newTrade = enterTrade(symbol, candles[ii-1], candles[ii], direction, session)
        if bool(newTrade):
            trades.append(newTrade)        

    

for trade in trades:
    printTrade(trade)





