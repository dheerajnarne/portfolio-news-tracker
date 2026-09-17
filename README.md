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

## Sheet columns

`ticker, title, source, link, published_date, fetched_at, priority, matched_terms, volume_spike`

- **priority**: `RED` (downgrade/fraud/resignation/bankruptcy/lawsuit/etc.),
  `GREEN` (buyback/results beat/upgrade/dividend/etc.), `EVENT`
  (merger/acquisition/IPO/stock split/etc.), or blank for routine news.
- **matched_terms**: which keyword(s) triggered the priority tag.
- **volume_spike**: flags a ticker when this run's article count is 3x+ its
  average hourly count so far today (needs at least 2 prior runs today and
  3+ articles this run to avoid noise on thin data).
- Sources now also include **NSE Announcements** — official exchange filings
  (results, insider trades, credit rating actions) for NSE-listed holdings,
  pulled directly from nseindia.com's public API.

## Known caveats

- **GitHub Actions free-tier minutes are a real constraint at hourly cadence.**
  With ~26 tickers × 4 sources (Google News, Bing News, Yahoo Finance, NSE
  Announcements), a run currently takes roughly 2–3 minutes; at 24 runs/day
  that's ~1,500–2,200 minutes/month against the 2,000 free minutes/month for
  private repos — workable today, but there's limited headroom. If you add
  significantly more tickers, watch **Settings → Billing → Actions usage**,
  and consider switching the cron to every 2 hours (`0 */2 * * *`) or making
  the repo public (unlimited Actions minutes) if you outgrow the budget.
- **NSE Announcements requires an unauthenticated session with nseindia.com**,
  which is known to sometimes block traffic from cloud-hosted IPs (including
  GitHub Actions runners). It's wrapped the same way every other source is —
  if it gets blocked, you'll see a `[warn]` line in the logs but the rest of
  the run still succeeds.
