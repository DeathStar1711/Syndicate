"""
Tools available to LangGraph agents (Phase 4 Agentic Browsing).

Search priority:
  1. Tavily Search (AI-native, returns rich summaries) — requires TAVILY_API_KEY
  2. DuckDuckGo News (ddgs) — free, no key, but rate-limited
  3. Google News RSS — free, no key, titles only (no summaries)
"""
import os
import re
import time
from typing import List, Dict, Any
from src.utils.logger import get_logger

logger = get_logger("stock_ai.tools")


def _resolve_company_name(query: str) -> str:
    """Try to resolve an obscure ticker to a human-readable company name."""
    try:
        import yfinance as yf
        ticker_guess = query.split()[0]
        if not ticker_guess.endswith(".NS") and not ticker_guess.endswith(".BO"):
            ticker_guess += ".NS"
        stock = yf.Ticker(ticker_guess)
        company_name = stock.info.get('shortName') or stock.info.get('longName')
        if company_name:
            short_name = company_name.upper().replace("LTD.", "").replace("LIMITED", "").replace("LTD", "")
            short_name = re.sub(r'[^A-Z0-9\s]', ' ', short_name).strip()
            return short_name
    except Exception:
        pass
    return ""


def _format_results(results: List[Dict], source_label: str = "") -> str:
    """Format a list of result dicts into a string for LLM consumption."""
    prefix = f"⚠️ {source_label}\n\n" if source_label else ""
    formatted = []
    for i, res in enumerate(results, 1):
        title = res.get("title", "No Title")
        body = res.get("body", res.get("content", res.get("summary", "")))
        url = res.get("url", res.get("href", ""))
        date = res.get("date", res.get("published_date", ""))
        source = res.get("source", "")
        formatted.append(
            f"Result {i}:\n"
            f"Title: {title}\n"
            f"Source: {source} ({date})\n"
            f"URL: {url}\n"
            f"Summary: {body or 'No summary available'}\n"
        )
    return prefix + "\n".join(formatted)


# ── Tier 1: Intelligent Web Search (yFinance + Google News) ──────────────────────────────
def _search_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    Search using yfinance for specific tickers (rich summaries, no limits) 
    and fallback to gnews for generic Google searches (no 429 rate limits).
    """
    formatted_results = []
    
    # Check if query contains a ticker (e.g. RELIANCE.NS)
    ticker_match = re.search(r"([A-Z0-9\-]+\.NS|[A-Z0-9\-]+\.BO)", query)
    if ticker_match:
        try:
            import yfinance as yf
            ticker = ticker_match.group(1)
            stock = yf.Ticker(ticker)
            news = stock.news
            for item in news[:max_results]:
                content = item.get("content", {})
                if not content: # Sometimes it's flat
                    content = item
                
                provider = content.get("provider", {})
                url_obj = content.get("clickThroughUrl", {}) or content.get("canonicalUrl", {})
                
                formatted_results.append({
                    "title": content.get("title", ""),
                    "body": content.get("summary", ""),
                    "url": url_obj.get("url", ""),
                    "source": provider.get("displayName", "Yahoo Finance"),
                    "date": content.get("pubDate", ""),
                })
            if formatted_results:
                logger.info(f"yFinance News: {len(formatted_results)} results for '{ticker}'")
                return formatted_results
        except Exception as e:
            logger.warning(f"yFinance news failed for '{query}': {e}")
            
    # Fallback to gnews for generic queries or if yfinance failed
    try:
        from gnews import GNews
        google_news = GNews(max_results=max_results)
        clean_query = query.replace(".NS", "").replace(".BO", "").replace("EQ", "").strip()
        
        results = google_news.get_news(clean_query)
        for item in results:
            formatted_results.append({
                "title": item.get("title", ""),
                "body": item.get("description", "No summary available. Visit URL."),
                "url": item.get("url", ""),
                "source": item.get("publisher", {}).get("title", "Google News"),
                "date": item.get("published date", "")
            })
            
        if formatted_results:
            logger.info(f"Google News (gnews): {len(formatted_results)} results for '{clean_query}'")
            return formatted_results
    except Exception as e:
        logger.warning(f"gnews search failed for '{query}': {e}")

    return []

# ── Tier 2: DuckDuckGo News ───────────────────────────────────────────

def _search_ddg(query: str, max_results: int = 5) -> List[Dict]:
    """
    Search via DuckDuckGo news. Free but prone to rate limiting.
    Returns [] on failure.
    """
    try:
        from ddgs import DDGS
        time.sleep(2.0)  # Rate limit protection

        clean_query = query.replace(".NS", "").replace(".BO", "").replace("EQ", "").strip()

        with DDGS() as ddgs:
            results = list(ddgs.news(clean_query, max_results=max_results))

        if results:
            logger.info(f"DDG News: {len(results)} results for '{clean_query}'")
            return results

        # If no results, try with resolved company name
        company_name = _resolve_company_name(query)
        if company_name:
            fallback_query = f"{company_name} stock news"
            logger.info(f"DDG empty for '{clean_query}'. Retrying with: '{fallback_query}'")
            time.sleep(1.5)
            with DDGS() as ddgs:
                results = list(ddgs.news(fallback_query, max_results=max_results))
            if results:
                logger.info(f"DDG News (company fallback): {len(results)} results")
                return results

        return []
    except Exception as e:
        logger.warning(f"DDG search failed for '{query}': {e}")
        return []


# ── Tier 3: Google News RSS ───────────────────────────────────────────

def _search_google_rss(query: str, max_results: int = 5) -> List[Dict]:
    """
    Fallback to Google News RSS. Titles only, no summaries.
    Returns [] on failure.
    """
    try:
        clean_query = query.replace(".NS", "").replace(".BO", "").replace("EQ", "").strip()

        # Try with resolved company name for better results
        company_name = _resolve_company_name(query)
        search_term = company_name if company_name else clean_query

        from src.data.news import fetch_news
        internal_news = fetch_news(search_term, days=7, max_headlines=max_results)

        if internal_news:
            logger.info(f"Google RSS: {len(internal_news)} results for '{search_term}'")
            return [
                {
                    "title": item.get("title", ""),
                    "body": "",  # RSS has no summaries
                    "url": item.get("url", ""),
                    "source": item.get("source", ""),
                    "date": item.get("published_date", ""),
                }
                for item in internal_news
            ]
        return []
    except Exception as e:
        logger.warning(f"Google RSS failed for '{query}': {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────

def perform_web_search(query: str, max_results: int = 5) -> str:
    """
    Search for stock news using a 3-tier fallback strategy:
      1. Tavily (AI-native, rich summaries)
      2. DuckDuckGo News (free, decent)
      3. Google News RSS (free, titles only)

    Returns a formatted markdown string of results, ready for LLM consumption.
    """
    logger.info(f"Agentic Web Search: '{query}'")

    # Tier 1: General Web Search (Snippets & Links)
    results = _search_web(query, max_results)
    if results:
        return _format_results(results)

    # Tier 2: DuckDuckGo News
    results = _search_ddg(query, max_results)
    if results:
        return _format_results(results)

    # Tier 3: Google News RSS
    results = _search_google_rss(query, max_results)
    if results:
        return _format_results(results, "DuckDuckGo Search Failed. Using Google News RSS Fallback:")

    return f"No web search results found for query: '{query}'"
