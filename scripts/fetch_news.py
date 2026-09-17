"""Fetch recent news links for each stock in portfolio.csv and append new
(deduped) rows to a Google Sheet. Designed to run unattended via GitHub
Actions, but works the same way run locally.
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import gspread
import requests

PORTFOLIO_PATH = "portfolio.csv"
HEADERS = ["ticker", "title", "source", "link", "published_date", "fetched_at"]

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioNewsBot/1.0)"}
REQUEST_TIMEOUT = 10  # seconds
PER_SOURCE_ENTRY_LIMIT = 15
DELAY_BETWEEN_REQUESTS = 1.5  # seconds, politeness between feed fetches


def google_news_url(ticker, company_name):
    query = f'"{ticker}" stock when:2d'
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def yahoo_finance_url(ticker, company_name):
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


def nasdaq_url(ticker, company_name):
    return f"https://www.nasdaq.com/feed/rssoutbound?symbol={ticker}"


def seeking_alpha_url(ticker, company_name):
    return f"https://seekingalpha.com/api/sa/combined/{ticker}.xml"


# Google News RSS aggregates hundreds of outlets on its own; the other three
# are best-effort bonus sources and may fail intermittently (that's fine —
# every fetch below is isolated so one bad source never kills the run).
SOURCES = {
    "Google News": google_news_url,
    "Yahoo Finance": yahoo_finance_url,
    "Nasdaq": nasdaq_url,
    "Seeking Alpha": seeking_alpha_url,
}


def read_portfolio(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        stocks = []
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            stocks.append((ticker, (row.get("company_name") or "").strip()))
        return stocks


def fetch_feed(source_name, url):
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[warn] {source_name}: HTTP fetch failed ({exc})", file=sys.stderr)
        return []

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        print(f"[warn] {source_name}: unparseable feed ({parsed.bozo_exception})", file=sys.stderr)
        return []

    return parsed.entries[:PER_SOURCE_ENTRY_LIMIT]


def entry_to_row(ticker, source_name, entry, fetched_at):
    link = getattr(entry, "link", "").strip()
    if not link:
        return None
    title = getattr(entry, "title", "").strip()
    published = getattr(entry, "published", "") or getattr(entry, "updated", "")
    return [ticker, title, source_name, link, published, fetched_at], link


def get_worksheet():
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    creds_path = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    worksheet_name = os.environ.get("GOOGLE_WORKSHEET_NAME", "Sheet1")

    gc = gspread.service_account(filename=creds_path)
    sh = gc.open_by_key(sheet_id)
    return sh.worksheet(worksheet_name)


def load_existing_links(worksheet):
    values = worksheet.get_all_values()
    if not values:
        worksheet.append_row(HEADERS)
        return set()

    header = values[0]
    if header != HEADERS:
        link_idx = header.index("link") if "link" in header else None
    else:
        link_idx = HEADERS.index("link")

    if link_idx is None:
        return set()

    return {row[link_idx].strip() for row in values[1:] if len(row) > link_idx and row[link_idx]}


def main():
    stocks = read_portfolio(PORTFOLIO_PATH)
    if not stocks:
        print("No tickers found in portfolio.csv")
        return

    worksheet = get_worksheet()
    seen_links = load_existing_links(worksheet)
    new_rows = []

    for ticker, company_name in stocks:
        for source_name, url_builder in SOURCES.items():
            url = url_builder(ticker, company_name)
            try:
                entries = fetch_feed(source_name, url)
            except Exception as exc:  # noqa: BLE001 - one bad source must never kill the run
                print(f"[warn] {source_name} failed for {ticker}: {exc}", file=sys.stderr)
                entries = []

            fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for entry in entries:
                result = entry_to_row(ticker, source_name, entry, fetched_at)
                if not result:
                    continue
                row, link = result
                if link in seen_links:
                    continue
                seen_links.add(link)
                new_rows.append(row)

            time.sleep(DELAY_BETWEEN_REQUESTS)

    if new_rows:
        worksheet.append_rows(new_rows, value_input_option="RAW")
        print(f"Appended {len(new_rows)} new rows.")
    else:
        print("No new articles found.")


if __name__ == "__main__":
    main()
