from datetime import datetime, timedelta
import MarketTimeManager as mtm

d = datetime(2022, 12, 23, 13, 30, 0)
print("Current date: " + str(d))
market_time_manager = mtm.MarketTimeManager()
(thisClose, nextOpen) = market_time_manager.getCandleChange(d.timestamp(), 'w')

print("Candle close: " + str(datetime.fromtimestamp(thisClose)))
print("Next candle open: " + str(datetime.fromtimestamp(nextOpen)))
