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
HEADERS = [
    "ticker", "title", "source", "link", "published_date", "fetched_at",
    "priority", "matched_terms", "volume_spike",
]

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioNewsBot/1.0)"}
REQUEST_TIMEOUT = 8  # seconds
PER_SOURCE_ENTRY_LIMIT = 15
DELAY_BETWEEN_REQUESTS = 0.5  # seconds, politeness between feed fetches
MAX_ARTICLE_AGE_HOURS = 24  # discard anything older - feeds' own "recency" query hints aren't hard filters

# --- Keyword/event alert tagging -------------------------------------------

RED_KEYWORDS = [
    "downgrade", "downgrades", "downgraded", "fraud", "scam",
    "resignation", "resigns", "resigned", "steps down",
    "bankruptcy", "insolvency", "insolvent",
    "sebi probe", "sebi investigation", "regulatory probe",
    "lawsuit", "sued", "investigation", "probe", "raid",
    "penalty", "fined", "fine imposed", "ban", "banned",
    "delisting", "delisted", "default", "defaults",
    "layoffs", "layoff", "job cuts", "net loss", "loss widens",
    "profit warning", "credit rating cut", "rating downgrade",
]

GREEN_KEYWORDS = [
    "buyback", "share buyback", "results beat", "beats estimates",
    "beat estimates", "upgrade", "upgrades", "upgraded", "bonus issue",
    "record profit", "profit jumps", "profit surges", "profit soars",
    "strong quarter", "outperform", "target price raised",
    "price target raised", "order win", "wins order", "bags order",
    "stake buy", "dividend declared", "special dividend",
    "credit rating upgrade",
]

EVENT_KEYWORDS = [
    "merger", "merges", "acquisition", "acquires", "acquire", "to acquire",
    "stake sale", "stake purchase", "ipo", "stock split", "demerger",
    "joint venture",
]


def classify_headline(title):
    lowered = title.lower()
    for label, keywords in (("RED", RED_KEYWORDS), ("GREEN", GREEN_KEYWORDS), ("EVENT", EVENT_KEYWORDS)):
        matched = [kw for kw in keywords if kw in lowered]
        if matched:
            return label, ", ".join(matched)
    return "", ""


# --- Volume-spike detection --------------------------------------------------

SPIKE_MULTIPLIER = 3
SPIKE_MIN_COUNT = 3  # this run must have at least this many articles for a ticker before a spike is meaningful
SPIKE_MIN_HISTORY_HOURS = 2  # need at least this many prior hourly runs today to trust the baseline


def detect_spike(current_count, baseline_total, prior_hours):
    if current_count < SPIKE_MIN_COUNT or prior_hours < SPIKE_MIN_HISTORY_HOURS:
        return ""
    baseline_avg = baseline_total / prior_hours
    if baseline_avg == 0:
        return f"SPIKE (new surge, {current_count} articles)"
    ratio = current_count / baseline_avg
    if ratio >= SPIKE_MULTIPLIER:
        return f"SPIKE ({ratio:.1f}x normal)"
    return ""


# --- RSS sources (Google News, Bing News, Yahoo Finance) --------------------


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
# feed for US tickers. Nasdaq, Seeking Alpha, and NSE Announcements were all
# tried and dropped: Nasdaq timed out on every request, Seeking Alpha 404'd
# on every request, and NSE's API got blocked when called from GitHub
# Actions runners - pure wasted time with hourly runs on a free minutes
# budget, and zero results either way.
SOURCES = {
    "Google News": google_news_url,
    "Bing News": bing_news_url,
    "Yahoo Finance": yahoo_finance_url,
}


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


# --- Shared row-building / sheet helpers -------------------------------------


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


def make_row(ticker, source_name, link, title, published_at, published_str, fetched_at, cutoff):
    link = (link or "").strip()
    if not link:
        return None
    if published_at is None or published_at < cutoff:
        return None  # too old, or undated and unverifiable - skip to keep the sheet fresh
    title = (title or "").strip()
    return [ticker, title, source_name, link, published_str, fetched_at], link


def get_spreadsheet():
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    creds_path = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    gc = gspread.service_account(filename=creds_path)
    return gc.open_by_key(sheet_id)


def get_or_create_daily_worksheet(sh, date_str):
    try:
        ws = sh.worksheet(date_str)
        if ws.row_values(1) != HEADERS:
            ws.update(range_name="A1", values=[HEADERS])
        return ws
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=date_str, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        return ws


def read_worksheet_stats(worksheet):
    """Links, per-ticker row counts, and distinct fetched_at hour-buckets in a worksheet."""
    values = worksheet.get_all_values()
    if not values:
        return set(), {}, set()

    header = values[0]
    link_idx = header.index("link") if "link" in header else None
    ticker_idx = header.index("ticker") if "ticker" in header else None
    fetched_idx = header.index("fetched_at") if "fetched_at" in header else None

    links = set()
    ticker_counts = {}
    hour_buckets = set()
    for row in values[1:]:
        if link_idx is not None and len(row) > link_idx and row[link_idx]:
            links.add(row[link_idx].strip())
        if ticker_idx is not None and len(row) > ticker_idx and row[ticker_idx]:
            t = row[ticker_idx].strip()
            ticker_counts[t] = ticker_counts.get(t, 0) + 1
        if fetched_idx is not None and len(row) > fetched_idx and row[fetched_idx]:
            hour_buckets.add(row[fetched_idx][:13])  # "YYYY-MM-DDTHH"

    return links, ticker_counts, hour_buckets


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

    today_links, today_ticker_counts, today_hour_buckets = read_worksheet_stats(today_ws)
    prior_hours = len(today_hour_buckets)

    # Nothing older than MAX_ARTICLE_AGE_HOURS is ever added, so checking
    # today's + yesterday's tab is enough to dedup across the day boundary.
    seen_links = set(today_links)
    try:
        yesterday_links, _, _ = read_worksheet_stats(sh.worksheet(yesterday_str))
        seen_links |= yesterday_links
    except WorksheetNotFound:
        pass

    candidates = []  # rows without priority/matched_terms/volume_spike yet
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
                result = make_row(
                    ticker, source_name,
                    getattr(entry, "link", ""),
                    getattr(entry, "title", ""),
                    entry_published_at(entry),
                    getattr(entry, "published", "") or getattr(entry, "updated", ""),
                    fetched_at, cutoff,
                )
                if not result:
                    continue
                row, link = result
                if link in seen_links:
                    continue
                seen_links.add(link)
                candidates.append(row)

            time.sleep(DELAY_BETWEEN_REQUESTS)

    if not candidates:
        print("No new articles found.")
        return

    current_counts = {}
    for row in candidates:
        current_counts[row[0]] = current_counts.get(row[0], 0) + 1

    spike_labels = {
        ticker: detect_spike(count, today_ticker_counts.get(ticker, 0), prior_hours)
        for ticker, count in current_counts.items()
    }

    new_rows = []
    for row in candidates:
        ticker, title = row[0], row[1]
        priority, matched_terms = classify_headline(title)
        new_rows.append(row + [priority, matched_terms, spike_labels.get(ticker, "")])

    today_ws.append_rows(new_rows, value_input_option="RAW")
    print(f"Appended {len(new_rows)} new rows to '{today_str}'.")
    for ticker, label in spike_labels.items():
        if label:
            print(f"[spike] {ticker}: {label}")


if __name__ == "__main__":
    main()
