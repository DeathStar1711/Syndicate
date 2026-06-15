"""
LLM-powered mistake post-mortem analysis.
Replaces simple rule-based classification with deep contextual analysis.
"""
from typing import Dict, Optional
from src.llm.client import get_llm_client
from src.llm.prompts import MISTAKE_ANALYSIS_PROMPT, SYSTEM_FINANCIAL_ANALYST
from src.utils.logger import get_logger

logger = get_logger("stock_ai.llm")


def analyze_mistake(
    trade_result: Dict,
    technical_snapshot: Dict,
    news_context: str = "No news data available",
    market_context: str = "No market context available",
    rule_based_codes: str = "unknown",
) -> Optional[Dict]:
    """
    Use Gemma 4 E4B to perform deep post-mortem on a losing trade.

    Args:
        trade_result: Dict with trade details (entry/exit prices, P&L, etc.)
        technical_snapshot: Technical indicators at entry time
        news_context: Formatted news around the trade dates
        market_context: Market conditions during the trade
        rule_based_codes: Comma-separated rule-based failure codes from V1

    Returns:
        Deep analysis dict or None if LLM unavailable
    """
    client = get_llm_client()
    if not client.is_healthy():
        return None

    # Format technical snapshot
    tech_str = "\n".join(
        f"  - {k}: {v}" for k, v in technical_snapshot.items()
    ) if technical_snapshot else "  No technical data available"

    prompt = MISTAKE_ANALYSIS_PROMPT.format(
        ticker=trade_result.get("ticker", "?"),
        direction=trade_result.get("direction", "long"),
        entry_price=trade_result.get("entry_price", 0),
        exit_price=trade_result.get("exit_price", 0),
        entry_date=trade_result.get("entry_date", "?"),
        exit_date=trade_result.get("exit_date", "?"),
        exit_reason=trade_result.get("exit_reason", "stop_loss"),
        pnl=trade_result.get("pnl", 0),
        pnl_pct=trade_result.get("pnl_pct", 0),
        stop_loss=trade_result.get("stop_loss", 0),
        technical_snapshot=tech_str,
        news_context=news_context,
        market_context=market_context,
        rule_based_codes=rule_based_codes,
    )

    # Don't cache mistake analyses — they're unique events
    result = client.generate_json(prompt, system=SYSTEM_FINANCIAL_ANALYST, use_cache=False)

    if result is None:
        logger.warning(f"LLM mistake analysis failed for {trade_result.get('ticker')}")
        return None

    logger.info(
        f"LLM mistake analysis for {trade_result.get('ticker')}: "
        f"Primary cause: {result.get('primary_cause', '?')[:60]} | "
        f"Severity: {result.get('severity', '?')}"
    )

    return result
