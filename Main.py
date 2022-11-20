# Import the client
from td.client import TDClient
import datetime
import time
import ticker

# Create a new session, credentials path is required.
TDSession = TDClient(
    client_id='DLGHTG07LAMJSNLDPD0VGAHEZJZVTMYD',
    redirect_uri='http://127.0.0.1',
    credentials_path='/Users/ilya/Git/StratBot_Sema/td_state.json'
)

# Login to the session
TDSession.login()
#price_history_service = TDSession.price_history()
#quote_service = TDSession.quotes()

# Grab real-time quotes for 'MSFT' (Microsoft)
#msft_quotes = TDSession.get_quotes(instruments=['MSFT'])
# Grab real-time quotes for 'AMZN' (Amazon) and 'SQ' (Square)
#multiple_quotes = TDSession.get_quotes(instruments=['AMZN','SQ'])
#candle = TDSession.get_price_history(symbol="MSFT", period_type="month", period=1, start_date=None, end_date=None, frequency_type="daily", frequency=1, extended_hours=False)
#print(candle)

# get quotes over fixed period of time
#startTime = "01/11/2022"
#endTime = "03/11/2022"
#startTime_stamp = int(datetime.datetime.strptime(startTime, "%d/%m/%Y").timestamp()*1000)
#endTime_stamp = int(datetime.datetime.strptime(endTime, "%d/%m/%Y").timestamp()*1000)
#candle2 = TDSession.get_price_history(symbol="MSFT", period_type="year", start_date=startTime_stamp, end_date=endTime_stamp, frequency_type="monthly", frequency=1, extended_hours=False)

t = ticker.Ticker("MSFT", TDSession)
print(t.to_string())
