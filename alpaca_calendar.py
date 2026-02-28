from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest
from alpaca.trading.models import Calendar
from typing import cast, List
import pandas as pd
from alpaca_config import alpaca_config
import pytz
# Set up the client
trading_client = TradingClient(alpaca_config['key'], alpaca_config['secret_key'])  # or paper=False for live
start_date = pd.to_datetime('2025-01-01 12:00:00')
end_date = pd.to_datetime('2025-01-10 5:00:00')
calendar = cast(List[Calendar], trading_client.get_calendar(GetCalendarRequest(start=start_date.date(), end=end_date.date())))
tz = pytz.timezone('America/New_York')
df = pd.DataFrame([{'market_open': tz.localize(c.open), 'market_close': tz.localize(c.close)} for c in calendar])
#print(calendar)
print(df)
'''
# Check if market was open on a specific date
target_date = date(2025, 1, 9)
calendar_request = GetCalendarRequest(start=target_date, end=target_date)
calendar = trading_client.get_calendar(calendar_request)

if calendar:
    print(f"Market was open on {calendar[0].date} from {calendar[0].open} to {calendar[0].close}")
else:
    print("Market was closed on this date.")

'''

