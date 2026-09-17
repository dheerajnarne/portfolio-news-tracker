"""Fetch recent news links for each stock in portfolio.csv and append new
(deduped) rows into today's dated worksheet of a Google Sheet. Designed to
run hourly via GitHub Actions, but works the same way run locally.
"""

import calendar
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import gspread
import requests
from gspread.exceptions import WorksheetNotFound

PORTFOLIO_PATH = "portfolio.csv"
HEADERS = ["ticker", "title", "source", "link", "published_date", "fetched_at"]

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioNewsBot/1.0)"}
REQUEST_TIMEOUT = 8  # seconds
PER_SOURCE_ENTRY_LIMIT = 15
DELAY_BETWEEN_REQUESTS = 0.5  # seconds, politeness between feed fetches
MAX_ARTICLE_AGE_HOURS = 24  # discard anything older - feeds' own "recency" query hints aren't hard filters


def google_news_url(ticker, company_name):
    query = f'"{ticker}" stock when:2d'
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def bing_news_url(ticker, company_name):
    query = f'"{ticker}" stock'
    return f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"


def yahoo_finance_url(ticker, company_name):
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


# Google News and Bing News are both broad search-based aggregators covering
# hundreds of outlets each (and largely different indexes from one another),
# so together they're the reliable backbone. Yahoo Finance is a bonus direct
# feed for US tickers. Nasdaq and Seeking Alpha were tried and dropped: in
# production runs Nasdaq timed out on every single request and Seeking Alpha
# 404'd on every single request - pure wasted time with hourly runs on a
# free minutes budget, and zero results either way.
SOURCES = {
    "Google News": google_news_url,
    "Bing News": bing_news_url,
    "Yahoo Finance": yahoo_finance_url,
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


def entry_published_at(entry):
    """Aware UTC datetime for the entry, or None if the feed didn't supply one."""
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not struct:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)


def entry_to_row(ticker, source_name, entry, fetched_at, cutoff):
    link = getattr(entry, "link", "").strip()
    if not link:
        return None

    published_at = entry_published_at(entry)
    if published_at is None or published_at < cutoff:
        return None  # too old, or undated and unverifiable - skip to keep the sheet fresh

    title = getattr(entry, "title", "").strip()
    published = getattr(entry, "published", "") or getattr(entry, "updated", "")
    return [ticker, title, source_name, link, published, fetched_at], link


def get_spreadsheet():
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    creds_path = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    gc = gspread.service_account(filename=creds_path)
    return gc.open_by_key(sheet_id)


def get_or_create_daily_worksheet(sh, date_str):
    try:
        return sh.worksheet(date_str)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=date_str, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        return ws


def links_in_worksheet(worksheet):
    values = worksheet.get_all_values()
    if not values:
        return set()
    header = values[0]
    if "link" not in header:
        return set()
    link_idx = header.index("link")
    return {row[link_idx].strip() for row in values[1:] if len(row) > link_idx and row[link_idx]}


def main():
    stocks = read_portfolio(PORTFOLIO_PATH)
    if not stocks:
        print("No tickers found in portfolio.csv")
        return

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff = now - timedelta(hours=MAX_ARTICLE_AGE_HOURS)

    sh = get_spreadsheet()
    today_ws = get_or_create_daily_worksheet(sh, today_str)

    # Nothing older than MAX_ARTICLE_AGE_HOURS is ever added, so checking
    # today's + yesterday's tab is enough to dedup across the day boundary.
    seen_links = links_in_worksheet(today_ws)
    try:
        seen_links |= links_in_worksheet(sh.worksheet(yesterday_str))
    except WorksheetNotFound:
        pass

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
                result = entry_to_row(ticker, source_name, entry, fetched_at, cutoff)
                if not result:
                    continue
                row, link = result
                if link in seen_links:
                    continue
                seen_links.add(link)
                new_rows.append(row)

            time.sleep(DELAY_BETWEEN_REQUESTS)

    if new_rows:
        today_ws.append_rows(new_rows, value_input_option="RAW")
        print(f"Appended {len(new_rows)} new rows to '{today_str}'.")
    else:
        print("No new articles found.")


if __name__ == "__main__":
    main()
