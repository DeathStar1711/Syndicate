"""
Rule-based strategy engine.
Evaluates multiple technical factors and produces a composite confidence score.
Collects both pros (reasons) and cons (risks) for each trade.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from src.utils.logger import get_logger
from src.utils.helpers import load_config
from src.features.sentiment import get_combined_sentiment

logger = get_logger("stock_ai.strategy")


class StrategyEngine:
    """
    Rule-based trading strategy that evaluates trend, momentum,
    volume, and volatility to produce trade signals with confidence scores.
    Each signal includes both pros (reasons to buy) and cons (risk factors).
    """

    def __init__(self, config: Optional[dict] = None):
        if config is None:
            full_config = load_config()
            self.config = full_config.get("strategy", {})
            self.capital_config = full_config.get("capital", {})
        else:
            self.config = config.get("strategy", config)
            self.capital_config = config.get("capital", {})

    def evaluate(self, df: pd.DataFrame, ticker: str) -> Optional[Dict]:
        """
        Evaluate a stock and return a trade signal if criteria are met.
        
        Args:
            df: DataFrame with all indicators computed
            ticker: Stock ticker symbol
        
        Returns:
            Trade signal dictionary or None if no signal
        """
        if df is None or len(df) < 200:
            logger.debug(f"{ticker}: Insufficient data ({len(df) if df is not None else 0} rows)")
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Skip if extreme volatility
        if latest.get("volatility_regime") == "extreme":
            logger.debug(f"{ticker}: Skipping — extreme volatility regime")
            return None

        # Get sentiment (live news + earnings check)
        sentiment = get_combined_sentiment(ticker, use_llm=False)
        if sentiment.get("avoid_trading"):
            logger.debug(f"{ticker}: Skipping — sentiment says avoid (earnings/news)")
            return None

        # Check minimum confidence threshold
        min_confidence = self.config.get("min_confidence", 55)
        
        # Determine direction FIRST so we can score properly
        direction = self._determine_direction(latest)
        if direction == "none":
            return None

        # Score each factor — now returns (score, pros, cons)
        scores = {}
        reasons = []
        cons = []

        # 1. Trend Alignment (0-25 points)
        trend_score, trend_pros, trend_cons = self._score_trend(latest, direction)
        scores["trend"] = trend_score
        reasons.extend(trend_pros)
        cons.extend(trend_cons)

        # 2. Momentum (0-25 points)
        momentum_score, momentum_pros, momentum_cons = self._score_momentum(latest, prev, direction)
        scores["momentum"] = momentum_score
        reasons.extend(momentum_pros)
        cons.extend(momentum_cons)

        # 3. Volume Confirmation (0-20 points)
        volume_score, volume_pros, volume_cons = self._score_volume(latest)
        scores["volume"] = volume_score
        reasons.extend(volume_pros)
        cons.extend(volume_cons)

        # 4. Volatility Regime (0-15 points)
        volatility_score, vol_pros, vol_cons = self._score_volatility(latest)
        scores["volatility"] = volatility_score
        reasons.extend(vol_pros)
        cons.extend(vol_cons)

        # 5. Sentiment bonus (0-15 points)
        sentiment_score, sent_pros, sent_cons = self._score_sentiment(sentiment, direction)
        scores["sentiment"] = sentiment_score
        reasons.extend(sent_pros)
        cons.extend(sent_cons)

        # Total composite score
        total_score = sum(scores.values())

        if total_score < min_confidence:
            logger.debug(f"{ticker}: Score {total_score} below threshold {min_confidence}")
            return None

        # Re-enabling the long-only restriction as per user request
        if direction != "long":
            logger.debug(f"{ticker}: Skipping — only long trades allowed")
            return None

        # Build signal — use live traded price as entry (what you'd actually pay)
        try:
            from src.data.fetcher import get_current_price
            live_price = get_current_price(ticker, use_live_api=True)
            if live_price and live_price > 0:
                entry_price = live_price
            else:
                entry_price = float(latest["close"])
                logger.warning(f"{ticker}: Live price unavailable, using historical close ₹{entry_price:.2f}")
        except Exception as e:
            entry_price = float(latest["close"])
            logger.debug(f"{ticker}: Live price fetch failed ({e}), using historical close")
        
        atr = float(latest["atr"]) if not pd.isna(latest.get("atr", np.nan)) else entry_price * 0.02

        sl_multiplier = self.config.get("atr_sl_multiplier", 1.5)
        target_multiplier = self.config.get("atr_target_multiplier", 3.0)
        min_rr = self.config.get("min_risk_reward", 2.0)

        if direction == "long":
            stop_loss = round(entry_price - (atr * sl_multiplier), 2)
            target = round(entry_price + (atr * target_multiplier), 2)
            risk_reward = round((target - entry_price) / max(entry_price - stop_loss, 0.01), 2)
        elif direction == "short":
            stop_loss = round(entry_price + (atr * sl_multiplier), 2)
            target = round(entry_price - (atr * target_multiplier), 2)
            risk_reward = round((entry_price - target) / max(stop_loss - entry_price, 0.01), 2)
        else:
            return None

        if risk_reward < min_rr:
            logger.debug(f"{ticker}: R:R {risk_reward} below minimum {min_rr}")
            return None

        signal = {
            "ticker": ticker,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward": risk_reward,
            "confidence": total_score,
            "scores": scores,
            "reasons": reasons,
            "cons": cons,
            "atr": round(atr, 2),
            "trend": str(latest.get("trend", "unknown")),
            "rsi": round(float(latest.get("rsi_14", 50)), 2),
            "volume_ratio": round(float(latest.get("volume_ratio", 1.0)), 2),
            "volatility_regime": str(latest.get("volatility_regime", "normal")),
            "sentiment_score": round(sentiment.get("combined_score", 0), 4),
            "news_headline_count": sentiment.get("news", {}).get("headline_count", 0),
            "latest_news_headline": sentiment.get("news", {}).get("latest_headline"),
        }

        logger.info(
            f"SIGNAL: {ticker} {direction.upper()} @ ₹{entry_price:.2f} | "
            f"SL: ₹{stop_loss:.2f} | Target: ₹{target:.2f} | "
            f"R:R: {risk_reward:.1f} | Confidence: {total_score}/100 | "
            f"Pros: {len(reasons)} | Cons: {len(cons)}"
        )

        return signal

    def _score_trend(self, latest: pd.Series, direction: str) -> Tuple[int, List[str], List[str]]:
        """Score trend alignment (0-25 points). Returns (score, pros, cons)."""
        score = 0
        pros = []
        cons = []
        
        is_long = direction == "long"

        # Price vs EMA 20
        if (latest["close"] > latest.get("ema_20", 0)) if is_long else (latest["close"] < latest.get("ema_20", 0)):
            score += 5
            pros.append("Price aligned with EMA 20")
        else:
            cons.append("Price counter to EMA 20 — short-term weakness")

        # Price vs EMA 50
        if (latest["close"] > latest.get("ema_50", 0)) if is_long else (latest["close"] < latest.get("ema_50", 0)):
            score += 5
            pros.append("Price aligned with EMA 50")
        else:
            cons.append("Price counter to EMA 50 — medium-term weakness")

        # Price vs EMA 200
        if (latest["close"] > latest.get("ema_200", 0)) if is_long else (latest["close"] < latest.get("ema_200", 0)):
            score += 8
            pros.append("Price aligned with EMA 200 (long-term trend)")
        else:
            cons.append("Price counter to EMA 200")

        # EMA alignment
        aligned = (latest.get("ema_9", 0) > latest.get("ema_20", 0) > latest.get("ema_50", 0)) if is_long else (latest.get("ema_9", 0) < latest.get("ema_20", 0) < latest.get("ema_50", 0))
        if aligned:
            score += 7
            pros.append("EMAs perfectly aligned")
        else:
            cons.append("EMAs not fully aligned")

        return min(score, 25), pros, cons

    def _score_momentum(self, latest: pd.Series, prev: pd.Series, direction: str) -> Tuple[int, List[str], List[str]]:
        """Score momentum indicators (0-25 points). Returns (score, pros, cons)."""
        score = 0
        pros = []
        cons = []
        
        is_long = direction == "long"
        rsi = latest.get("rsi_14", 50)

        # RSI favorable
        if is_long:
            if 40 <= rsi <= 65:
                score += 10
                pros.append(f"RSI {rsi:.0f} in optimal long zone (40-65)")
            elif 30 <= rsi < 40:
                score += 6
                pros.append(f"RSI {rsi:.0f} near oversold — potential reversal")
            elif rsi > 70:
                cons.append(f"RSI {rsi:.0f} overbought — risk of pullback")
            elif rsi > 65:
                cons.append(f"RSI {rsi:.0f} approaching overbought territory")
            elif rsi < 30:
                cons.append(f"RSI {rsi:.0f} deeply oversold — falling knife risk")
        else:
            if 35 <= rsi <= 60:
                score += 10
                pros.append(f"RSI {rsi:.0f} in optimal short zone (35-60)")
            elif 60 < rsi <= 70:
                score += 6
                pros.append(f"RSI {rsi:.0f} near overbought — potential reversal")
            elif rsi < 30:
                cons.append(f"RSI {rsi:.0f} oversold — risk of bounce")
            elif rsi > 70:
                cons.append(f"RSI {rsi:.0f} deeply overbought — squeeze risk")

        # MACD bullish
        macd_hist = latest.get("macd_histogram", 0)
        if (macd_hist > 0) if is_long else (macd_hist < 0):
            score += 7
            pros.append("MACD histogram aligned with direction")
        else:
            cons.append("MACD histogram counter to direction")

        # MACD crossover
        crossover = latest.get("macd_crossover", 0)
        prev_crossover = prev.get("macd_crossover", 0)
        target_crossover = 1 if is_long else -1
        
        if crossover == target_crossover:
            score += 8
            pros.append("MACD crossover in our direction")
        elif prev_crossover == target_crossover:
            score += 5
            pros.append("Recent MACD crossover in our direction")
        elif crossover == -target_crossover:
            cons.append("MACD crossover counter to direction")

        return min(score, 25), pros, cons

    def _score_volume(self, latest: pd.Series) -> Tuple[int, List[str], List[str]]:
        """Score volume confirmation (0-20 points). Returns (score, pros, cons)."""
        score = 0
        pros = []
        cons = []

        volume_ratio = latest.get("volume_ratio", 1.0)
        breakout_threshold = self.config.get("volume_breakout_ratio", 1.2)

        if volume_ratio >= breakout_threshold * 1.5:
            score += 15
            pros.append(f"Strong volume surge ({volume_ratio:.1f}x average)")
        elif volume_ratio >= breakout_threshold:
            score += 10
            pros.append(f"Above-average volume ({volume_ratio:.1f}x)")
        elif volume_ratio >= 0.8:
            score += 5
            pros.append("Normal volume")
        else:
            cons.append(f"Low volume ({volume_ratio:.1f}x) — weak participation")

        # Volume trend
        if latest.get("volume_trend", 0) > 0:
            score += 5
            pros.append("Increasing volume trend")
        elif latest.get("volume_trend", 0) < 0:
            cons.append("Declining volume trend — conviction fading")

        return min(score, 20), pros, cons

    def _score_volatility(self, latest: pd.Series) -> Tuple[int, List[str], List[str]]:
        """Score volatility regime (0-15 points). Returns (score, pros, cons)."""
        regime = latest.get("volatility_regime", "normal")
        pros = []
        cons = []

        if regime == "low":
            pros.append("Low volatility — favorable for breakout entries")
            return 15, pros, cons
        elif regime == "normal":
            pros.append("Normal volatility — standard conditions")
            return 10, pros, cons
        elif regime == "high":
            cons.append("High volatility — wider stops needed, larger risk")
            return 5, pros, cons
        else:  # extreme
            cons.append("Extreme volatility — very high risk environment")
            return 0, pros, cons

    def _score_sentiment(self, sentiment: Dict, direction: str) -> Tuple[int, List[str], List[str]]:
        """Score sentiment data (0-15 points). Returns (score, pros, cons)."""
        score = 8  # Neutral default
        pros = []
        cons = []
        
        is_long = direction == "long"
        combined = sentiment.get("combined_score", 0)
        headline_count = sentiment.get("news", {}).get("headline_count", 0)
        
        # Flip sentiment if shorting
        adj_combined = combined if is_long else -combined

        if adj_combined > 0.3:
            score = 15
            pros.append(f"Strong supporting sentiment ({combined:+.2f})")
        elif adj_combined > 0:
            score = 10
            pros.append(f"Mildly supporting sentiment ({combined:+.2f})")
        elif adj_combined < -0.3:
            score = 0
            cons.append(f"Strong opposing sentiment ({combined:+.2f})")
        elif adj_combined < 0:
            score = 5
            cons.append(f"Mildly opposing sentiment ({combined:+.2f})")

        if headline_count == 0:
            cons.append("No recent news — limited sentiment data")

        return score, pros, cons

    def _determine_direction(self, latest: pd.Series) -> str:
        """Determine trade direction based on overall trend."""
        trend = latest.get("trend", "sideways")
        strong_trend = latest.get("strong_trend", "neutral")

        if trend == "bullish" and strong_trend == "bullish":
            return "long"
        elif trend == "bearish" and strong_trend == "bearish":
            return "short"
        elif trend == "bullish":
            return "long"
        else:
            return "none"
