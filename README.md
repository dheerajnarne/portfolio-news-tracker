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

## Known caveats

- **GitHub Actions free-tier minutes are a real constraint at hourly cadence.**
  With ~26 tickers × 3 sources (Google News, Bing News, Yahoo Finance), a run
  currently takes roughly 1.5–2.5 minutes; at 24 runs/day that's
  ~1,100–1,800 minutes/month against the 2,000 free minutes/month for
  private repos — workable today, but there's limited headroom. If you add
  significantly more tickers, watch **Settings → Billing → Actions usage**,
  and consider switching the cron to every 2 hours (`0 */2 * * *`) or making
  the repo public (unlimited Actions minutes) if you outgrow the budget.
