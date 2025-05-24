import pandas as pd
import MarketTimeManager as mtm
# Parsing CSV of earnings calendar
# Column names are: 
#   act_symbol - ticker
#   date - date of earnings
#   when - before market open (BMO) or after market close (AMC)
class EarningsCalendar:
    def __init__(self, inputFile, market_time_manager=None):
        df = pd.read_csv(inputFile, keep_default_na=False, na_values=[''])
        # Ensure 'date' is a datetime type for proper sorting
        df['date'] = pd.to_datetime(df['date'], format='%m/%d/%y')
        # Sort by ticker and date so previous/next make sense
        df = df.sort_values(['act_symbol', 'date'])
        # Replace empty strings with pd.NA so we can use ffill/bfill
        df['when'] = df['when'].replace('', pd.NA)
        # Fill missing AMC/BMO for each ticker
        df['when'] = (
            df.groupby('act_symbol')['when']
            .ffill()  # forward fill (use previous ER)
            .bfill()  # backward fill (use next ER)
        )
        #df['lastDateBeforeER'] = pd.NA
        if market_time_manager is None:
            market_time_manager = mtm.MarketTimeManager()
        # Fill lastDateBeforeER with the last date before earnings date
        df['lastDateBeforeER'] = df.apply(
            lambda row: self._fill_last_date_before_er(row['date'], row['when'], market_time_manager), axis=1
        )
        # Now convert to dictionary of dictionaries
        #result = df.set_index(['act_symbol', 'date'])['when'].to_dict()
            #.unstack(level=0)  # optional, for inspection
            #.stack()           # revert back to Series with MultiIndex
            #.to_dict()         # now it's a flat dict with (name, date): comment
        #)
        # Convert to desired nested structure: { name: { date: comment } }
        #nested_dict = defaultdict(dict)
        #for (name, date), time in result.items():
        #    nested_dict[name][date] = time
        # Convert defaultdict to regular dict
        #nested_dict = dict(nested_dict)
        df.drop(columns=['date', 'when'], inplace=True)
        self.full_calendar = df
    # Function to fill lastDateBeforeER
    def _fill_last_date_before_er(self, date, er_time, market_time_manager):
        if er_time == 'After market close':
            return date.date()  # same day, so return date
        else:   # befor market open on that day - need to return previous trading day
            er_day = market_time_manager.getCandleOpenCloseTime(date.timestamp(), 'd', n_pre=1, n_post=0)
            return er_day['pre'][0][0].date()
         
    def get_ER_by_ticker(self, ticker):
        if self.full_calendar is not None:
            return self.full_calendar.where(self.full_calendar['act_symbol'] == ticker)['lastDateBeforeER'].dropna().values.tolist()
        else:
            raise ValueError("Data not loaded. Please load data first.")

if __name__ == "__main__":
    # Example usage
    inputFile = '/Users/ilyatoytman/Git/stratBot/EarningsCalendar_2025-05-18.csv'
    ticker = 'ZION'
    er = EarningsCalendar(inputFile)
    er_by_ticker = er.get_ER_by_ticker(ticker)
    print(er_by_ticker)
    print('====')
    print(er.full_calendar.iloc[40:60])      
    # check if date is right before ER
    for date_to_check in ['2024-01-22', '2024-04-19', '2024-04-21', '2024-04-22']:
        if pd.to_datetime(date_to_check).date() in er_by_ticker:
            print(f"Date {date_to_check} is right before ER for ticker {ticker}.")
        else:
            print(f"Date {date_to_check} is NOT right before ER for ticker {ticker}.")




