from datetime import datetime, timedelta
import util

d = datetime(2022, 12, 23, 13, 30, 0)
print("Current date: " + str(d))
(thisClose, nextOpen) = util.getCandleChange_ms(1000*d.timestamp(), 'w')

print("Candle close: " + str(datetime.fromtimestamp(thisClose/1000)))
print("Next candle open: " + str(datetime.fromtimestamp(nextOpen/1000)))
