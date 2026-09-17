# Portfolio News Aggregator

Runs hourly (free, via GitHub Actions) and appends new news article links for
every stock in `portfolio.csv` into a dated tab of a Google Sheet.

## How it works

- `portfolio.csv` is your portfolio — one row per stock.
- `scripts/fetch_news.py` pulls recent articles per ticker from Google News
  RSS (which itself aggregates hundreds of outlets — Reuters, CNBC,
  Bloomberg, MarketWatch, Motley Fool, Benzinga, Seeking Alpha, Investing.com,
  etc.) plus three direct feeds (Yahoo Finance, Nasdaq, Seeking Alpha) as
  bonus redundancy.
- Only articles published within the last 24 hours are kept — a feed's own
  "recent" query hint (e.g. Google's `when:2d`) is just a ranking bias, not a
  hard filter, so the script checks each entry's real publish date itself.
- The sheet gets one new tab per day, named `YYYY-MM-DD` (UTC), created
  automatically the first time news lands on that day.
- New links (not already in today's or yesterday's tab) are appended as rows:
  `ticker, title, source, link, published_date, fetched_at`.
- `.github/workflows/fetch_news.yml` runs the script once an hour, on the
  hour (UTC), and can also be triggered manually from the Actions tab.

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

## One-time Google Sheets setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/),
   create (or reuse) a project, and enable the **Google Sheets API** for it.
2. Under **IAM & Admin → Service Accounts**, create a new service account.
3. Open the service account → **Keys → Add Key → JSON**, and download the
   key file. Keep this file private — never commit it.
4. Create a Google Sheet in your own Google account (this is where the news
   links will land).
5. Click **Share** on that sheet and paste in the service account's
   `client_email` (found in the JSON key file, looks like
   `xxx@yyy.iam.gserviceaccount.com`), grant it **Editor** access.
6. Copy the Sheet ID from its URL:
   `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.

## One-time GitHub setup

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**, add:

- `GCP_SERVICE_ACCOUNT_JSON` — paste the *entire contents* of the JSON key
  file downloaded above.
- `GOOGLE_SHEET_ID` — the Sheet ID from step 6 above.

Push this repo to GitHub. The workflow will run automatically on schedule,
or you can trigger it manually from the **Actions** tab → "Fetch Portfolio
News" → **Run workflow**.

## Running locally

```powershell
$env:GOOGLE_SHEET_ID = "<your sheet id>"
$env:GOOGLE_SERVICE_ACCOUNT_FILE = "C:\path\to\service_account.json"
pip install -r requirements.txt
python scripts/fetch_news.py
```

## Known caveats

- **Nasdaq and Seeking Alpha feeds fail intermittently** (bot protection on
  their end) — this is expected and non-fatal; you'll see a `[warn]` line in
  the logs but the run still succeeds using the other sources.
- **Google News links are Google's redirect URLs**, not the publisher's
  canonical link — so the same article reached via Google News vs. a direct
  feed can appear as two separate rows. Dedup is by exact link, not by
  underlying article.
- The spreadsheet gains one new tab per day indefinitely; there's no
  automatic archiving/trimming of old daily tabs in this version.
- Hourly runs use roughly 1,400–1,500 GitHub Actions minutes/month (24 runs
  a day × ~2 min each), comfortably under the 2,000 free minutes/month for
  private repos — but there's little headroom if the run gets slower, so
  keep an eye on **Settings → Billing → Actions usage** if you add many more
  tickers or sources.
