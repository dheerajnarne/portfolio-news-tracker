# Portfolio News Aggregator

Runs hourly (free, via GitHub Actions) and appends new news article links for
every stock in `portfolio.csv` into a dated tab of a Google Sheet.
## Google Sheets Link:
https://docs.google.com/spreadsheets/d/1rjj6S28Kfo6TstTkD7GTDvfi5JFWHvVjbALqhOUS_iA/edit?gid=0#gid=0
## Adding to your portfolio

Just edit `portfolio.csv` and commit:

```csv
ticker,company_name
AAPL,Apple Inc
MSFT,Microsoft Corporation
GOOGL,Alphabet Inc
```

Add a row to track a new stock, delete a row to stop tracking one. No other
setup is needed for portfolio changes.
