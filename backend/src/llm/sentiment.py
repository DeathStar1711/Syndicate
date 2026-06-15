"""
LLM-powered sentiment analysis.
Replaces the keyword-based approach from V1 with Gemma 4 E4B semantic analysis.
Falls back to keyword-based if Ollama is unavailable.
"""
from typing import Dict, List, Optional
from src.llm.client import get_llm_client
from src.llm.prompts import SENTIMENT_ANALYSIS_PROMPT, SYSTEM_FINANCIAL_ANALYST
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.llm")

# Ticker to company name mapping (common NSE stocks)
_TICKER_NAMES = {
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "HDFCBANK.NS": "HDFC Bank",
    "INFY.NS": "Infosys",
    "ICICIBANK.NS": "ICICI Bank",
    "SBIN.NS": "State Bank of India",
    "BHARTIARTL.NS": "Bharti Airtel",
    "ITC.NS": "ITC Ltd",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "BAJFINANCE.NS": "Bajaj Finance",
    "MARUTI.NS": "Maruti Suzuki",
    "TATAMOTORS.NS": "Tata Motors",
    "SUNPHARMA.NS": "Sun Pharma",
    "WIPRO.NS": "Wipro",
    "AXISBANK.NS": "Axis Bank",
    "TATASTEEL.NS": "Tata Steel",
    "NTPC.NS": "NTPC Ltd",
    "ADANIENT.NS": "Adani Enterprises",
    "LT.NS": "Larsen & Toubro",
}


def _get_company_name(ticker: str) -> str:
    """Get company name from ticker, fallback to cleaning the ticker."""
    if ticker in _TICKER_NAMES:
        return _TICKER_NAMES[ticker]
    # Clean .NS/.BO suffix
    return ticker.replace(".NS", "").replace(".BO", "")


def analyze_sentiment_llm(
    ticker: str,
    headlines: List[Dict],
) -> Optional[Dict]:
    """
    Use Gemma 4 E4B to analyze news sentiment for a stock.

    Args:
        ticker: Stock ticker symbol
        headlines: List of headline dicts with 'title' key

    Returns:
        Structured sentiment dict or None if LLM unavailable
    """
    if not headlines:
        return None

    client = get_llm_client()
    if not client.is_healthy():
        return None

    # Format headlines for the prompt
    headline_text = "\n".join(
        f"- {h.get('title', 'N/A')} (Source: {h.get('source', 'Unknown')})"
        for h in headlines[:10]
    )

    prompt = SENTIMENT_ANALYSIS_PROMPT.format(
        ticker=ticker,
        company_name=_get_company_name(ticker),
        headlines=headline_text,
    )

    result = client.generate_json(prompt, system=SYSTEM_FINANCIAL_ANALYST)

    if result is None:
        logger.warning(f"LLM sentiment analysis failed for {ticker}")
        return None

    # Validate and normalize the response
    valid_sentiments = {
        "strongly_positive", "positive", "neutral", "negative", "strongly_negative"
    }
    if result.get("overall_sentiment") not in valid_sentiments:
        result["overall_sentiment"] = "neutral"

    # Clamp score
    score = result.get("sentiment_score", 0.0)
    result["sentiment_score"] = max(-1.0, min(1.0, float(score)))

    logger.info(
        f"LLM sentiment for {ticker}: {result['overall_sentiment']} "
        f"(score={result['sentiment_score']:.2f}) — {result.get('reasoning', '')[:80]}"
    )

    return result
