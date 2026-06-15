"""
Test suite for strategy engine.
"""
import sys
import os
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.rules import StrategyEngine
from src.features.technical import compute_all_indicators


def create_bullish_data(n=300):
    """Create sample data with a clear uptrend for testing signal generation."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    
    # Steady uptrend
    base = 100
    prices = []
    for i in range(n):
        price = base + (i * 0.2) + np.random.normal(0, 1)
        prices.append(max(price, 10))
    
    close = pd.Series(prices, index=dates)
    high = close * (1 + abs(np.random.normal(0.005, 0.003, n)))
    low = close * (1 - abs(np.random.normal(0.005, 0.003, n)))
    volume = np.random.randint(500000, 5000000, n)
    
    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume,
    }, index=dates)
    
    return df


class TestStrategyEngine:
    def setup_method(self):
        self.config = {
            "strategy": {
                "ema_fast": 9, "ema_medium": 20, "ema_slow": 50, "ema_trend": 200,
                "rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "atr_sl_multiplier": 1.5, "atr_target_multiplier": 3.0,
                "volume_sma_period": 20, "volume_breakout_ratio": 1.2,
                "volatility_low": 25, "volatility_high": 75, "volatility_extreme": 90,
                "min_confidence": 55, "max_signals": 5, "min_risk_reward": 2.0,
            },
            "capital": {
                "starting_amount": 100000, "max_risk_per_trade_pct": 0.02,
                "max_position_pct": 0.20, "max_open_positions": 5,
            }
        }
        self.engine = StrategyEngine(self.config)

    def test_engine_initializes(self):
        assert self.engine is not None
        assert self.engine.config is not None

    def test_insufficient_data_returns_none(self):
        df = create_bullish_data(50)  # Not enough data
        df = compute_all_indicators(df, self.config["strategy"])
        result = self.engine.evaluate(df, "TEST.NS")
        assert result is None

    def test_signal_structure(self):
        df = create_bullish_data(300)
        df = compute_all_indicators(df, self.config["strategy"])
        result = self.engine.evaluate(df, "TEST.NS")
        
        # May or may not generate a signal depending on data
        if result is not None:
            assert "ticker" in result
            assert "entry_price" in result
            assert "stop_loss" in result
            assert "target" in result
            assert "risk_reward" in result
            assert "confidence" in result
            assert "reasons" in result
            assert result["stop_loss"] < result["entry_price"]
            assert result["target"] > result["entry_price"]
            assert result["confidence"] >= 55
            assert result["risk_reward"] >= 2.0

    def test_confidence_range(self):
        df = create_bullish_data(300)
        df = compute_all_indicators(df, self.config["strategy"])
        result = self.engine.evaluate(df, "TEST.NS")
        
        if result is not None:
            assert 0 <= result["confidence"] <= 100


class TestStrategySignalGeneration:
    def test_none_data_handled(self):
        engine = StrategyEngine()
        result = engine.evaluate(None, "TEST.NS")
        assert result is None

    def test_empty_data_handled(self):
        engine = StrategyEngine()
        result = engine.evaluate(pd.DataFrame(), "TEST.NS")
        assert result is None
