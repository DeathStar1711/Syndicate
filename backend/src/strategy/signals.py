"""
Morning signal generator.
Fetches latest data, computes indicators, runs strategy, and returns top trade ideas.
"""
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime
from src.data.fetcher import fetch_batch
from src.features.technical import compute_all_indicators
from src.strategy.rules import StrategyEngine
from src.strategy.position_sizing import calculate_position_size, calculate_risk_reward
from src.utils.logger import get_logger
from src.utils.helpers import load_config, get_tickers, now_ist
import random

logger = get_logger("stock_ai.strategy")


def generate_signals(
    tickers: Optional[List[str]] = None,
    config: Optional[dict] = None,
) -> List[Dict]:
    """
    Generate morning trade signals for the given watchlist.
    
    This is the main entry point for the morning signal generation workflow.
    Fetches latest data, computes indicators, evaluates strategy rules,
    and returns the top 3-5 ranked trade recommendations.
    
    Args:
        tickers: List of ticker symbols (uses watchlist if None)
        config: Configuration dict (loads from file if None)
    
    Returns:
        List of trade signal dictionaries, sorted by confidence (descending)
    """
    if config is None:
        config = load_config()
    
    if tickers is None:
        tickers = get_tickers()
    
    strategy_config = config.get("strategy", {})
    capital_config = config.get("capital", {})
    
    capital = capital_config.get("starting_amount", 100000)
    max_risk_pct = capital_config.get("max_risk_per_trade_pct", 0.02)
    max_position_pct = capital_config.get("max_position_pct", 0.20)
    max_signals = strategy_config.get("max_signals", 5)
    
    logger.info("=" * 70)
    logger.info(f"SIGNAL GENERATION — {now_ist().strftime('%Y-%m-%d %H:%M IST')}")
    logger.info(f"Analyzing {len(tickers)} stocks | Capital: ₹{capital:,.0f}")
    logger.info("=" * 70)
    
    # Step 0: Fundamental Pre-filtering
    if strategy_config.get("use_fundamental_filter", True):
        logger.info("Step 0: Pre-filtering tickers with strong fundamentals via Groww MCP...")
        try:
            from src.data.groww_mcp import fetch_fundamentals_screener_sync
            # Find large/mid cap stocks with strong fundamentals
            query = "Large cap stocks with high ROE, low debt to equity, high profit margins"
            results = fetch_fundamentals_screener_sync(query, max_results=50)
            if results:
                fundamental_tickers_list = []
                for r in results:
                    code = r.get("nse_script_code")
                    if code and f"{code}.NS" not in fundamental_tickers_list:
                        fundamental_tickers_list.append(f"{code}.NS")
                
                # Keep only those in our watchlist that passed the screen
                filtered_tickers = [t for t in tickers if t in fundamental_tickers_list]
                
                # If intersection is empty, pick a random sample of 15 fundamentally strong stocks
                if not filtered_tickers:
                    logger.info("Watchlist intersection empty. Replacing watchlist with a random subset of 15 fundamentally strong stocks.")
                    tickers = random.sample(fundamental_tickers_list, min(15, len(fundamental_tickers_list)))
                else:
                    logger.info(f"Fundamental filter applied. Kept {len(filtered_tickers)} out of {len(tickers)} tickers.")
                    tickers = filtered_tickers
        except Exception as e:
            logger.warning(f"Fundamental pre-filtering failed: {e}")

    # Step 1: Fetch latest data
    interval = strategy_config.get("interval", "1d")
    period = strategy_config.get("period", "1y")
    
    logger.info(f"Step 1: Fetching latest market data (Interval: {interval}, Period: {period})...")
    data = fetch_batch(tickers, period=period, interval=interval)
    
    if not data:
        logger.error("No data fetched — aborting signal generation")
        return []
    
    from src.data.fetcher import fetch_index
    logger.info("Fetching NIFTY 50 index data for relative strength benchmarking...")
    index_df = fetch_index("^NSEI", period=period)
    
    # Step 2: Compute indicators and generate signals
    logger.info("Step 2: Computing indicators and evaluating strategy...")
    engine = StrategyEngine(config)
    all_signals = []
    features_dict = {}
    
    from src.data.groww_mcp import GrowwMCPClient
    import asyncio
    
    client = GrowwMCPClient.get_instance()
    
    async def fetch_oi_batch(tickers):
        tasks = [client._get_open_interest_analysis_async(t.split(".")[0]) for t in tickers]
        return await asyncio.gather(*tasks, return_exceptions=True)

    oi_results = client.run_coroutine(fetch_oi_batch(list(data.keys()))) or []
    oi_data_map = {}
    for i, t in enumerate(data.keys()):
        oi_data_map[t] = oi_results[i] if i < len(oi_results) and not isinstance(oi_results[i], Exception) else {}

    for ticker, df in data.items():
        try:
            # Use pre-fetched OI data
            oi_data = oi_data_map.get(ticker, {})
            
            # Compute all technical indicators
            df_with_features = compute_all_indicators(df, strategy_config, oi_data=oi_data, index_df=index_df)
            features_dict[ticker] = df_with_features
            
            # Evaluate strategy
            signal = engine.evaluate(df_with_features, ticker)
            
            if signal is not None:
                # Position sizing will be calculated after ML adjustment
                signal["timestamp"] = now_ist().isoformat()
                
                # No legacy news fetching - this is handled by Agentic Web Browser
                signal["news_context"] = {"sentiment": "neutral", "headline": "To be fetched by AI"}
                
                all_signals.append(signal)
        
        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")
            continue
    
    # ---------------------------------------------------------
    # NEW: Adjust confidence with ML model
    # ---------------------------------------------------------
    try:
        from src.ml.predictor import MLPredictor
        ml_predictor = MLPredictor(config)
        all_signals = ml_predictor.batch_adjust(all_signals, features_dict)
    except Exception as e:
        logger.warning(f"ML adjustment failed: {e}")

    # ---------------------------------------------------------
    # Position Sizing (with Kelly Criterion based on ML Probabilities)
    # ---------------------------------------------------------
    for signal in all_signals:
        prob = signal.get("ml_probability")
        pos = calculate_position_size(
            capital=capital,
            entry_price=signal["entry_price"],
            stop_loss=signal["stop_loss"],
            max_risk_pct=max_risk_pct,
            max_position_pct=max_position_pct,
            win_probability=prob,
            risk_reward=signal.get("risk_reward")
        )
        signal["position"] = pos

    # Step 3: Rank and select top signals
    logger.info("Step 3: Ranking signals...")
    all_signals.sort(key=lambda x: x["confidence"], reverse=True)
    top_signals = all_signals[:max_signals]
    
    # Step 4: Log results
    logger.info("=" * 70)
    logger.info(f"RESULTS: {len(top_signals)} signals generated from {len(all_signals)} candidates")
    logger.info("=" * 70)
    
    for i, sig in enumerate(top_signals, 1):
        news = sig.get("news_context", {})
        headline = news.get("headline") or ""
        news_str = f"News: {news.get('sentiment', 'neutral').upper()} | {headline[:60]}..."
        
        # Add Key Events to Log
        key_events = news.get("key_events", [])
        if key_events:
            news_str += f"\n  ⚠️ KEY EVENT: {', '.join(key_events)}"
        
        logger.info(
            f"\n{'─' * 50}\n"
            f"  #{i} {sig['ticker']} — {sig['direction'].upper()}\n"
            f"  Entry: ₹{sig['entry_price']:.2f} | SL: ₹{sig['stop_loss']:.2f} | "
            f"Target: ₹{sig['target']:.2f}\n"
            f"  R:R: {sig['risk_reward']:.1f}:1 | Confidence: {sig['confidence']}/100\n"
            f"  Position: {sig['position']['shares']} shares (₹{sig['position']['position_value']:,.2f})\n"
            f"  Risk: ₹{sig['position']['risk_amount']:,.2f} ({sig['position']['risk_pct']:.1f}%)\n"
            f"  {news_str}\n"
            f"  Reasons: {' | '.join(sig['reasons'])}"
        )
    
    # Add disclaimer
    logger.info(
        f"\n{'═' * 70}\n"
        f"  ⚠ DISCLAIMER: These are paper trading signals for research only.\n"
        f"  They do not constitute financial advice and do not guarantee returns.\n"
        f"{'═' * 70}"
    )
    
    return top_signals


def format_signal_text(signal: Dict) -> str:
    """Format a signal into a readable text summary."""
    news = signal.get("news_context", {})
    sentiment_icon = "😐"
    if news.get("sentiment") == "positive":
        sentiment_icon = "🟢"
    elif news.get("sentiment") == "negative":
        sentiment_icon = "🔴"

    lines = [
        f"📊 {signal['ticker']} — {signal['direction'].upper()}",
        f"",
        f"  Entry Price:  ₹{signal['entry_price']:.2f}",
        f"  Stop-Loss:    ₹{signal['stop_loss']:.2f}",
        f"  Target:       ₹{signal['target']:.2f}",
        f"  Risk-Reward:  {signal['risk_reward']:.1f}:1",
        f"  Confidence:   {signal['confidence']}/100",
        f"",
        f"  Position Size: {signal['position']['shares']} shares",
        f"  Position Value: ₹{signal['position']['position_value']:,.2f}",
        f"  Capital at Risk: ₹{signal['position']['risk_amount']:,.2f} ({signal['position']['risk_pct']:.1f}%)",
        f"",
        f"  📰 Market Context:",
        f"  {sentiment_icon} Sentiment: {news.get('sentiment', 'neutral').title()} (Score: {news.get('score', 0):.2f})",
        f"  🗞 Headline: {news.get('headline', 'No recent news')}",
    ]

    # Add Key Events (Deep News)
    key_events = news.get("key_events", [])
    if key_events:
        event_str = ", ".join(key_events)
        lines.append(f"  ⚠️ KEY EVENT: {event_str}")

    lines.append("")
    lines.append(f"  Why this trade:")
    for reason in signal.get("reasons", []):
        lines.append(f"    ✓ {reason}")
    
    lines.append("")
    lines.append(f"  Trend: {signal.get('trend', '?')} | RSI: {signal.get('rsi', '?')} | "
                 f"Vol Ratio: {signal.get('volume_ratio', '?')}x | "
                 f"Volatility: {signal.get('volatility_regime', '?')}")
    
    return "\n".join(lines)
