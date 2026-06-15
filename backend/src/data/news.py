"""
News data acquisition module.
Fetches stock-related news headlines via Tiingo (primary),
Google News RSS (fallback), and NewsAPI (tertiary fallback).
Returns structured headline data for sentiment analysis and
post-mortem trade review.

Design: Graceful degradation — returns empty list on failure,
never blocks the trading pipeline.
"""
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import quote_plus

import requests

from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.data")

# Strip .NS / .BO suffix to get clean company name for news searches
_TICKER_CLEAN_RE = re.compile(r"\.(NS|BO)$")


def _clean_ticker_for_search(ticker: str) -> str:
    """Convert 'RELIANCE.NS' → '"RELIANCE" stock'."""
    name = _TICKER_CLEAN_RE.sub("", ticker)
    return f'"{name}" stock'


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RSS pubDate string into datetime."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None




# ── Google News RSS (fallback, no API key needed) ─────────────────────


def fetch_news_google_rss(
    ticker: str, max_results: int = 10, days: int = 3
) -> List[Dict]:
    """
    Fetch news headlines from Google News RSS feed.

    Args:
        ticker: Stock ticker symbol (e.g. 'RELIANCE.NS')
        max_results: Maximum headlines to return
        days: Look back N days

    Returns:
        List of headline dicts with keys: title, source, published_date, url
    """
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — pip install feedparser")
        return []

    query = _clean_ticker_for_search(ticker)
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"

    try:
        # Use requests for timeout control, then parse with feedparser
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        cutoff = datetime.now() - timedelta(days=days)
        headlines = []

        for entry in feed.entries[:max_results * 2]:  # fetch extra, then filter
            pub_date = _parse_rss_date(entry.get("published", ""))

            # Filter by recency
            if pub_date and pub_date.replace(tzinfo=None) < cutoff:
                continue

            headlines.append({
                "title": entry.get("title", "").strip(),
                "source": entry.get("source", {}).get("title", "Unknown"),
                "published_date": pub_date.isoformat() if pub_date else None,
                "url": entry.get("link", ""),
            })

            if len(headlines) >= max_results:
                break

        logger.debug(f"Google News RSS: {len(headlines)} headlines for {ticker}")
        return headlines

    except requests.Timeout:
        logger.warning(f"Google News RSS timed out for {ticker}")
        return []
    except Exception as e:
        logger.warning(f"Google News RSS failed for {ticker}: {e}")
        return []


# ── NewsAPI (tertiary fallback, requires NEWSAPI_KEY env var) ─────────


def fetch_news_newsapi(
    ticker: str, max_results: int = 10, days: int = 3
) -> List[Dict]:
    """
    Fetch news from NewsAPI.org (free tier: 100 req/day).

    Args:
        ticker: Stock ticker symbol
        max_results: Maximum headlines
        days: Look back N days

    Returns:
        List of headline dicts
    """
    config = load_config()
    news_config = config.get("news", {})
    api_key_env = news_config.get("newsapi_key_env", "NEWSAPI_KEY")
    api_key = os.environ.get(api_key_env)

    if not api_key:
        logger.debug("NewsAPI key not configured — skipping fallback")
        return []

    query = _clean_ticker_for_search(ticker)
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": from_date,
                "sortBy": "publishedAt",
                "pageSize": max_results,
                "language": "en",
                "apiKey": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        headlines = []
        for article in data.get("articles", []):
            pub = article.get("publishedAt")
            headlines.append({
                "title": (article.get("title") or "").strip(),
                "source": (article.get("source", {}) or {}).get("name", "Unknown"),
                "published_date": pub,
                "url": article.get("url", ""),
            })

        logger.debug(f"NewsAPI: {len(headlines)} headlines for {ticker}")
        return headlines

    except Exception as e:
        logger.warning(f"NewsAPI failed for {ticker}: {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────


def fetch_news(ticker: str, days: int = 3, max_headlines: int = 10) -> List[Dict]:
    """
    Fetch recent news headlines for a stock.
    Uses Tiingo first, falls back to Google News RSS, then NewsAPI.

    Args:
        ticker: Stock ticker symbol (e.g. 'RELIANCE.NS')
        days: Look back N days (default 3)
        max_headlines: Max headlines to return

    Returns:
        List of headline dicts: {title, source, published_date, url}
        Returns empty list on failure — never raises.
    """
    config = load_config()
    news_config = config.get("news", {})

    if not news_config.get("enabled", True):
        return []

    max_headlines = news_config.get("max_headlines", max_headlines)
    days = news_config.get("lookback_days", days)

    # Primary: NewsAPI
    headlines = fetch_news_newsapi(ticker, max_results=max_headlines, days=days)

    # Fallback: Google News RSS
    if not headlines:
        headlines = fetch_news_google_rss(ticker, max_results=max_headlines, days=days)

    return headlines


def fetch_news_for_event(
    ticker: str, event_date: str, window_days: int = 2
) -> List[Dict]:
    """
    Fetch news around a specific event date (for post-mortem analysis).

    Args:
        ticker: Stock ticker symbol
        event_date: ISO date string of the event (e.g. trade exit date)
        window_days: Days before/after to search

    Returns:
        List of headline dicts around the event date
    """
    try:
        event_dt = datetime.fromisoformat(event_date)
    except (ValueError, TypeError):
        event_dt = datetime.now()

    # Fetch a wider window and filter
    all_news = fetch_news(ticker, days=window_days * 2 + 1, max_headlines=20)

    # Filter to window around event
    window_start = event_dt - timedelta(days=window_days)
    window_end = event_dt + timedelta(days=window_days)

    filtered = []
    for item in all_news:
        pub = item.get("published_date")
        if pub:
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                pub_dt = pub_dt.replace(tzinfo=None)
                if window_start <= pub_dt <= window_end:
                    filtered.append(item)
            except (ValueError, TypeError):
                filtered.append(item)  # include if we can't parse the date
        else:
            filtered.append(item)  # include undated items

    logger.info(
        f"Post-mortem news for {ticker} around {event_date}: "
        f"{len(filtered)} headlines found"
    )
    return filtered
