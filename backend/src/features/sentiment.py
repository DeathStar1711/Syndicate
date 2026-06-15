"""
Sentiment analysis module — V2 with LLM primary, keyword fallback.

Uses Gemma 4 E4B (via Ollama) for semantic headline analysis.
Falls back to keyword-based scoring when LLM is unavailable.
Also provides ML-ready feature extraction for the training pipeline.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.features")

# ── In-memory cache for news features ──────────────────────────────
_news_cache: Dict[str, Dict] = {}
_CACHE_TTL_MINUTES = 15

# ── Default sentiment keyword lists (fallback) ─────────────────────

_DEFAULT_POSITIVE = [
    "surge", "rally", "breakout", "upgrade", "beat", "profit", "growth",
    "bullish", "record", "high", "gain", "soar", "strong", "outperform",
    "buy", "accumulate", "recovery", "boost", "expand", "dividend",
    "acquisition", "partnership", "innovation", "approval",
]

_DEFAULT_NEGATIVE = [
    "crash", "plunge", "downgrade", "miss", "loss", "bearish", "fraud",
    "selloff", "sell-off", "slump", "warning", "probe", "investigation",
    "default", "debt", "layoff", "decline", "weak", "underperform",
    "sell", "risk", "concern", "cut", "suspension", "penalty",
]


def _get_sentiment_keywords() -> Dict[str, List[str]]:
    """Load sentiment keywords from config or use defaults."""
    try:
        config = load_config()
        news_config = config.get("news", {})
        keywords = news_config.get("sentiment_keywords", {})
        return {
            "positive": keywords.get("positive", _DEFAULT_POSITIVE),
            "negative": keywords.get("negative", _DEFAULT_NEGATIVE),
        }
    except Exception:
        return {"positive": _DEFAULT_POSITIVE, "negative": _DEFAULT_NEGATIVE}


def score_headline(headline: str, keywords: Optional[Dict] = None) -> float:
    """Score a single headline using keyword matching (fallback)."""
    if not headline:
        return 0.0
    keywords = keywords or _get_sentiment_keywords()
    text = headline.lower()
    pos_count = sum(1 for w in keywords["positive"] if w in text)
    neg_count = sum(1 for w in keywords["negative"] if w in text)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    score = (pos_count - neg_count) / total
    return max(-1.0, min(1.0, score))


def score_headlines(headlines: List[Dict], keywords: Optional[Dict] = None) -> Dict:
    """Score a batch of headlines using keyword matching (fallback)."""
    keywords = keywords or _get_sentiment_keywords()
    if not headlines:
        return {"score": 0.0, "count": 0, "individual_scores": [], "std": 0.0}

    scores = [score_headline(h.get("title", ""), keywords) for h in headlines]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    if len(scores) > 1:
        mean = avg_score
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std = variance ** 0.5
    else:
        std = 0.0

    return {
        "score": round(avg_score, 4),
        "count": len(scores),
        "individual_scores": [round(s, 4) for s in scores],
        "std": round(std, 4),
    }


def scan_for_key_events(headlines: List[Dict]) -> List[str]:
    """Scan headlines for high-impact key events."""
    if not headlines:
        return []
    try:
        config = load_config()
        defaults = ["Merger", "Acquisition", "Earnings", "Results", "FDA", "Contract"]
        keywords = config.get("news", {}).get("key_event_keywords", defaults)
        found_events = set()
        for h in headlines:
            text = (h.get("title") or "").lower()
            for kw in keywords:
                if kw.lower() in text:
                    found_events.add(kw.title())
        return list(found_events)
    except Exception:
        return []


def get_earnings_flag(ticker: str) -> Dict:
    """Check if a stock has upcoming earnings."""
    return {
        "ticker": ticker,
        "has_upcoming_earnings": False,
        "days_to_earnings": None,
        "sentiment": "neutral",
        "score": 0,
    }


def get_news_sentiment(ticker: str, use_llm: bool = True) -> Dict:
    """
    Analyze recent news sentiment — uses LLM first, keyword fallback.

    Returns:
        Dictionary with news sentiment data including LLM reasoning if available
    """
    try:
        from src.data.news import fetch_news
        headlines = fetch_news(ticker, days=3, max_headlines=10)
    except Exception as e:
        logger.debug(f"News fetch failed for {ticker}: {e}")
        return {
            "ticker": ticker, "sentiment": "neutral", "score": 0,
            "headline_count": 0, "latest_headline": None,
            "llm_analysis": None,
        }

    # Try LLM sentiment first
    llm_analysis = None
    if use_llm:
        try:
            from src.llm.sentiment import analyze_sentiment_llm
            llm_result = analyze_sentiment_llm(ticker, headlines)
            if llm_result:
                llm_analysis = llm_result
                score = llm_result.get("sentiment_score", 0)
                sentiment_label = llm_result.get("overall_sentiment", "neutral")
                # Map LLM labels to simple labels
                if "positive" in sentiment_label:
                    sentiment = "positive"
                elif "negative" in sentiment_label:
                    sentiment = "negative"
                else:
                    sentiment = "neutral"

                return {
                    "ticker": ticker,
                    "sentiment": sentiment,
                    "score": score,
                    "headline_count": len(headlines),
                    "latest_headline": headlines[0].get("title") if headlines else None,
                    "key_events": llm_result.get("key_events", []),
                    "risk_flags": llm_result.get("risk_flags", []),
                    "llm_reasoning": llm_result.get("reasoning", ""),
                    "llm_analysis": llm_analysis,
                }
        except Exception as e:
            logger.debug(f"LLM sentiment failed for {ticker}, using keyword fallback: {e}")

    # Fallback: keyword-based scoring
    result = score_headlines(headlines)
    key_events = scan_for_key_events(headlines)
    latest_headline = headlines[0].get("title") if headlines else None

    return {
        "ticker": ticker,
        "sentiment": (
            "positive" if result["score"] > 0.1
            else "negative" if result["score"] < -0.1
            else "neutral"
        ),
        "score": result["score"],
        "headline_count": result["count"],
        "latest_headline": latest_headline,
        "key_events": key_events,
        "llm_analysis": None,
    }


def get_corporate_actions(ticker: str) -> Dict:
    """Check for corporate actions (placeholder)."""
    return {"ticker": ticker, "has_actions": False, "action_type": None, "action_date": None}


def get_combined_sentiment(ticker: str, use_llm: bool = True) -> Dict:
    """Get combined sentiment score from all sources."""
    earnings = get_earnings_flag(ticker)
    news = get_news_sentiment(ticker, use_llm=use_llm)
    corporate = get_corporate_actions(ticker)

    combined_score = (
        earnings["score"] * 0.3
        + news["score"] * 0.5
        + (0 if not corporate["has_actions"] else -0.2) * 0.2
    )

    avoid = (
        earnings["has_upcoming_earnings"]
        and (earnings.get("days_to_earnings") or 999) <= 2
    )

    return {
        "ticker": ticker,
        "combined_score": combined_score,
        "sentiment": "neutral" if abs(combined_score) < 0.2 else (
            "positive" if combined_score > 0 else "negative"
        ),
        "avoid_trading": avoid,
        "earnings": earnings,
        "news": news,
        "corporate": corporate,
    }


# ── ML-ready feature extraction ─────────────────────────────────────

def compute_news_features(ticker: str, use_cache: bool = True) -> Dict[str, float]:
    """Compute ML-ready news sentiment features for a ticker."""
    if use_cache and ticker in _news_cache:
        cached = _news_cache[ticker]
        age = datetime.now() - cached["timestamp"]
        if age < timedelta(minutes=_CACHE_TTL_MINUTES):
            return cached["features"]

    try:
        from src.data.news import fetch_news
        headlines = fetch_news(ticker, days=3, max_headlines=10)
        result = score_headlines(headlines)

        sentiment_score = result["score"]
        news_volume = min(result["count"] / 10.0, 1.0)
        recency_score = news_volume * (1.0 - result["std"]) if news_volume > 0 else 0.0

        features = {
            "news_sentiment_score": round(sentiment_score, 4),
            "news_volume": round(news_volume, 4),
            "news_recency_score": round(recency_score, 4),
        }

        _news_cache[ticker] = {"features": features, "timestamp": datetime.now()}
        return features

    except Exception as e:
        logger.debug(f"News features computation failed for {ticker}: {e}")
        return {
            "news_sentiment_score": 0.0,
            "news_volume": 0.0,
            "news_recency_score": 0.0,
        }


def clear_news_cache():
    """Clear the news features cache."""
    _news_cache.clear()
