"""
Intraday breakout scanner.
Runs every 15 minutes during market hours to detect exceptional opportunities.
Only alerts on stocks with significant price jumps + volume spikes.
"""
import pandas as pd
from typing import List, Dict, Optional
from src.data.fetcher import fetch_latest
from src.features.technical import compute_all_indicators
from src.strategy.position_sizing import calculate_position_size, calculate_risk_reward
from src.strategy.cooldown import get_cooled_tickers, record_batch
from src.utils.logger import get_logger
from src.utils.helpers import load_config, get_tickers, now_ist

logger = get_logger("stock_ai.strategy")

# Breakout thresholds
MIN_PRICE_JUMP_PCT = 2.0       # Minimum % move in last candle
MIN_VOLUME_SPIKE = 3.0         # Volume must be 3x average
MIN_CONFIDENCE = 75            # Only "too good to ignore"
MAX_BREAKOUT_SIGNALS = 3       # Max alerts per scan


class BreakoutScanner:
    """Scans for intraday breakout opportunities using 15-minute bars."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.capital_config = self.config.get("capital", {})
        self.capital = self.capital_config.get("starting_amount", 100000)
        self.max_risk_pct = self.capital_config.get("max_risk_per_trade_pct", 0.02)
        self.max_position_pct = self.capital_config.get("max_position_pct", 0.20)

    def scan(self, tickers: Optional[List[str]] = None) -> List[Dict]:
        """
        Scan for breakout signals across the watchlist.

        Returns:
            List of breakout signals, sorted by confidence (descending)
        """
        if tickers is None:
            tickers = get_tickers()

        # Exclude cooled tickers
        cooled = get_cooled_tickers()
        if cooled:
            tickers = [t for t in tickers if t not in cooled]
            logger.info(f"  Watchlist after cooldown: {len(tickers)} tickers")

        if not tickers:
            logger.info("No tickers to scan after cooldown filter")
            return []

        logger.info(f"🔍 Breakout scan: analyzing {len(tickers)} tickers...")

        signals = []
        for ticker in tickers:
            try:
                signal = self._analyze_ticker(ticker)
                if signal is not None:
                    signals.append(signal)
            except Exception as e:
                logger.debug(f"Error scanning {ticker}: {e}")
                continue

        # Sort by confidence and cap
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        top_signals = signals[:MAX_BREAKOUT_SIGNALS]

        if top_signals:
            logger.info(
                f"🚨 {len(top_signals)} breakout signals detected: "
                + ", ".join(f"{s['ticker']} (+{s['price_jump_pct']:.1f}%)" for s in top_signals)
            )
            # Record in cooldown
            record_batch([s["ticker"] for s in top_signals], trade_type="breakout")

        return top_signals

    def _analyze_ticker(self, ticker: str) -> Optional[Dict]:
        """Analyze a single ticker for breakout conditions."""

        # Fetch 15-min intraday data (last 5 days for context)
        df = fetch_latest(ticker, period="5d", interval="15m")
        if df is None or len(df) < 20:
            return None

        # Also fetch daily data for ATR and EMA context
        df_daily = fetch_latest(ticker, period="60d", interval="1d")
        if df_daily is None or len(df_daily) < 20:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = float(latest["close"])

        # ── Check 1: Price jump ──────────────────────────────
        price_change_pct = ((current_price - float(prev["close"])) / float(prev["close"])) * 100
        if abs(price_change_pct) < MIN_PRICE_JUMP_PCT:
            return None

        # ── Check 2: Volume spike ────────────────────────────
        # Average volume over last 20 candles (excluding current)
        recent_vol = df["volume"].iloc[-21:-1]
        avg_volume = float(recent_vol.mean()) if len(recent_vol) > 0 else 0
        current_volume = float(latest["volume"])

        if avg_volume <= 0:
            return None
        volume_ratio = current_volume / avg_volume
        if volume_ratio < MIN_VOLUME_SPIKE:
            return None

        # ── Passed breakout filters — build signal ───────────

        # Compute confidence score
        confidence = self._compute_confidence(
            price_change_pct, volume_ratio, df, df_daily
        )
        if confidence < MIN_CONFIDENCE:
            return None

        # ATR from daily data for stop-loss/target
        atr = self._compute_atr(df_daily)
        if atr <= 0:
            return None

        # Direction
        direction = "long" if price_change_pct > 0 else "short"

        # Stop-loss and target
        if direction == "long":
            stop_loss = round(current_price - 1.5 * atr, 2)
            target = round(current_price + 3.0 * atr, 2)
        else:
            stop_loss = round(current_price + 1.5 * atr, 2)
            target = round(current_price - 3.0 * atr, 2)

        risk_reward = calculate_risk_reward(current_price, stop_loss, target)

        # Position sizing
        position = calculate_position_size(
            capital=self.capital,
            entry_price=current_price,
            stop_loss=stop_loss,
            max_risk_pct=self.max_risk_pct,
            max_position_pct=self.max_position_pct,
        )

        # Build reasons and cons
        reasons = []
        cons = []

        reasons.append(
            f"🚨 Price surge: {price_change_pct:+.1f}% in last 15 minutes"
        )
        reasons.append(
            f"Volume spike: {volume_ratio:.1f}× average (institutional interest)"
        )

        # Check VWAP if available
        vwap = self._compute_vwap(df)
        if vwap and direction == "long" and current_price > vwap:
            reasons.append(f"Trading above VWAP (₹{vwap:.2f}) — bullish intraday bias")
        elif vwap and direction == "long" and current_price < vwap:
            cons.append(f"Below VWAP (₹{vwap:.2f}) — intraday trend not confirmed")

        # Check if price is above key daily EMAs
        if len(df_daily) >= 50:
            ema20 = float(df_daily["close"].ewm(span=20).mean().iloc[-1])
            ema50 = float(df_daily["close"].ewm(span=50).mean().iloc[-1])
            if current_price > ema20 and current_price > ema50:
                reasons.append("Above daily EMA 20 & EMA 50 — aligned with daily trend")
            elif current_price < ema50:
                cons.append("Below daily EMA 50 — might be a dead cat bounce")

        # Check RSI from daily data
        daily_indicators = compute_all_indicators(df_daily, self.config.get("strategy", {}))
        if daily_indicators is not None and "rsi" in daily_indicators.columns:
            rsi = float(daily_indicators["rsi"].iloc[-1])
            if rsi > 70:
                cons.append(f"Daily RSI {rsi:.0f} — overbought, higher reversal risk")
            elif 50 <= rsi <= 65:
                reasons.append(f"Daily RSI {rsi:.0f} — momentum confirming breakout")

        # Gap-up warning
        if price_change_pct > 5:
            cons.append(f"Extreme surge (+{price_change_pct:.1f}%) — gap risk, avoid chasing")

        return {
            "ticker": ticker,
            "direction": direction,
            "entry_price": current_price,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward": round(risk_reward, 1),
            "confidence": confidence,
            "price_jump_pct": round(price_change_pct, 1),
            "volume_ratio": round(volume_ratio, 1),
            "reasons": reasons,
            "cons": cons,
            "position": position,
            "trade_type": "breakout",
            "timestamp": now_ist().isoformat(),
        }

    def _compute_confidence(
        self, price_change_pct: float, volume_ratio: float,
        df_15m: pd.DataFrame, df_daily: pd.DataFrame,
    ) -> int:
        """Compute a confidence score (0-100) for the breakout."""
        score = 50  # Base

        # Price jump contribution (2-5% = 5-15 pts, >5% = 15 pts cap)
        price_pts = min(abs(price_change_pct) * 3, 15)
        score += price_pts

        # Volume spike contribution (3x = 5 pts, 5x+ = 15 pts)
        vol_pts = min((volume_ratio - 2) * 5, 15)
        score += vol_pts

        # Trend alignment bonus (daily EMA check)
        if len(df_daily) >= 50:
            close = float(df_daily["close"].iloc[-1])
            ema20 = float(df_daily["close"].ewm(span=20).mean().iloc[-1])
            ema50 = float(df_daily["close"].ewm(span=50).mean().iloc[-1])
            if close > ema20 > ema50:
                score += 10  # Strong trend alignment

        # Consecutive green candles bonus
        last_3 = df_15m["close"].iloc[-3:]
        if all(last_3.diff().dropna() > 0):
            score += 5

        return min(int(score), 100)

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Average True Range from daily data."""
        if len(df) < period + 1:
            return 0
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - close).abs(),
            (low - close).abs(),
        ], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    def _compute_vwap(self, df: pd.DataFrame) -> Optional[float]:
        """Compute VWAP for today's intraday data."""
        try:
            # Get today's data only
            today = df.index[-1].date() if hasattr(df.index[-1], "date") else None
            if today is None:
                return None
            today_df = df[df.index.date == today]  # type: ignore[attr-defined]
            if len(today_df) < 2:
                return None

            typical_price = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
            cumulative_tp_vol = (typical_price * today_df["volume"]).cumsum()
            cumulative_vol = today_df["volume"].cumsum()

            vwap_series = cumulative_tp_vol / cumulative_vol
            return float(vwap_series.iloc[-1])
        except Exception:
            return None
