"""
LLM-powered daily market briefing.
Generates a comprehensive morning overview of market conditions,
sector rotation, and trading recommendations.
"""
import time
from typing import Dict, Optional
from src.llm.client import get_llm_client
from src.llm.prompts import MARKET_BRIEFING_PROMPT, SYSTEM_MARKET_ANALYST
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.llm")

# In-memory cache for the briefing — TTL-based (1 hour)
_daily_briefing: Optional[Dict] = None
_briefing_timestamp: float = 0
_BRIEFING_TTL_SECONDS = 3600  # 1 hour


def generate_market_briefing(
    market_data: Dict,
    sector_performance: str = "No sector data available",
    market_headlines: str = "No headlines available",
    global_cues: str = "No global cues available",
) -> Optional[Dict]:
    """
    Generate a comprehensive morning market briefing using Gemma.

    Args:
        market_data: Dict with nifty_value, sensex_value, vix, etc.
        sector_performance: Formatted sector-wise returns
        market_headlines: Top market news headlines
        global_cues: Global market / overnight cues

    Returns:
        Market briefing dict or None if LLM unavailable
    """
    global _daily_briefing, _briefing_timestamp

    # Return cached briefing if still fresh
    if _daily_briefing is not None and (time.time() - _briefing_timestamp) < _BRIEFING_TTL_SECONDS:
        return _daily_briefing

    client = get_llm_client()
    if not client.is_healthy():
        return None

    vix_val = market_data.get("vix_value", 0)
    vix_regime = "low" if vix_val < 15 else "normal" if vix_val < 20 else "high" if vix_val < 25 else "extreme"

    prompt = MARKET_BRIEFING_PROMPT.format(
        nifty_value=market_data.get("nifty_value", "N/A"),
        nifty_change=market_data.get("nifty_change", "N/A"),
        sensex_value=market_data.get("sensex_value", "N/A"),
        sensex_change=market_data.get("sensex_change", "N/A"),
        vix_value=vix_val,
        vix_regime=vix_regime,
        nifty_above_ema50=market_data.get("nifty_above_ema50", "N/A"),
        nifty_above_ema200=market_data.get("nifty_above_ema200", "N/A"),
        sector_performance=sector_performance,
        market_headlines=market_headlines,
        global_cues=global_cues,
    )

    result = client.generate_json(prompt, system=SYSTEM_MARKET_ANALYST, use_cache=False)

    if result is None:
        logger.warning("Failed to generate market briefing")
        return None

    # Add metadata
    from src.utils.helpers import now_ist
    result["generated_at"] = now_ist().isoformat()
    result["date"] = now_ist().strftime("%Y-%m-%d")

    # Cache with TTL
    _daily_briefing = result
    _briefing_timestamp = time.time()

    logger.info(
        f"Market briefing generated: {result.get('market_mood', '?')} "
        f"(score={result.get('mood_score', 0):.2f})"
    )

    return result


def get_cached_briefing() -> Optional[Dict]:
    """Get the cached briefing if still within TTL."""
    if _daily_briefing is not None and (time.time() - _briefing_timestamp) < _BRIEFING_TTL_SECONDS:
        return _daily_briefing
    return None


def clear_briefing_cache():
    """Clear the cached briefing (forces regeneration)."""
    global _daily_briefing, _briefing_timestamp
    _daily_briefing = None
    _briefing_timestamp = 0
