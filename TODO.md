Here is a list of tasks that are in progress and ones that we will work on in the future

# In Progress
* Fixing issues with data being received from TDAmeritrade after trading hours (need to explicitly transfer start_date and end_date as parameters to get intraday data during the trading day, while during after-hours it's ok to just simply receive the data from the last trading day)
* Strategy based on strat patterns
* Log target prices and stop-losses
* Elements of watchlist are kept in toml file

# Future tasks
* Add handling of exceptions associated with loss of internet connection 
* More sophisticated way of checking when to insert a candle (currently used ms are not accurate, bcoz there might be 365 or 366 days in a year, 90 or 91 days in a quarter, 31 or 30 or 29 or 28 days in a month)
* Keep track of this candle close time and next candle open time outside (and independent of) ticker 
* Update all tickers concurrently (using processes, not threads)
* Go through all TODO
* Finish all descriptions
* Web app (or better just implement telegram bot?)
* Deploy the app (Digital Ocean? Amazon?)
* When detecting patterns - invalidate patterns that include candles from after close of short trading days 
* Change timeframes from strings to enum 
