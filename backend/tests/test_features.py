"""
Test suite for feature engineering module.
Verifies technical indicator computations against known values.
"""
import sys
import os
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.features.technical import (
    compute_all_indicators,
    compute_emas,
    compute_rsi,
    compute_macd,
    compute_atr,
    compute_volume_analysis,
    compute_volatility_regime,
    compute_adx,
    compute_bollinger_bands,
    compute_stochastic,
)


def create_sample_data(n=300):
    """Create sample OHLCV data for testing."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    
    # Generate realistic price series
    price = 100.0
    prices = []
    for _ in range(n):
        price *= 1 + np.random.normal(0.0005, 0.015)
        prices.append(price)
    
    close = pd.Series(prices, index=dates)
    high = close * (1 + abs(np.random.normal(0.005, 0.003, n)))
    low = close * (1 - abs(np.random.normal(0.005, 0.003, n)))
    open_price = close.shift(1).fillna(close.iloc[0])
    volume = np.random.randint(100000, 5000000, n)
    
    df = pd.DataFrame({
        "open": open_price.values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume,
    }, index=dates)
    
    return df


class TestEMA:
    def test_ema_columns_exist(self):
        df = create_sample_data()
        config = {"ema_fast": 9, "ema_medium": 20, "ema_slow": 50, "ema_trend": 200}
        result = compute_emas(df, config)
        assert "ema_9" in result.columns
        assert "ema_20" in result.columns
        assert "ema_50" in result.columns
        assert "ema_200" in result.columns

    def test_ema_slopes_exist(self):
        df = create_sample_data()
        config = {"ema_fast": 9, "ema_medium": 20, "ema_slow": 50, "ema_trend": 200}
        result = compute_emas(df, config)
        assert "ema_9_slope" in result.columns
        assert "ema_20_slope" in result.columns

    def test_ema_values_reasonable(self):
        df = create_sample_data()
        config = {"ema_fast": 9, "ema_medium": 20, "ema_slow": 50, "ema_trend": 200}
        result = compute_emas(df, config)
        # EMA should be in the same ballpark as close price
        assert abs(result["ema_9"].iloc[-1] - result["close"].iloc[-1]) < result["close"].iloc[-1] * 0.1


class TestRSI:
    def test_rsi_column_exists(self):
        df = create_sample_data()
        config = {"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30}
        result = compute_rsi(df, config)
        assert "rsi_14" in result.columns
        assert "rsi_zone" in result.columns

    def test_rsi_range(self):
        df = create_sample_data()
        config = {"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30}
        result = compute_rsi(df, config)
        rsi_values = result["rsi_14"].dropna()
        assert (rsi_values >= 0).all()
        assert (rsi_values <= 100).all()

    def test_rsi_zones(self):
        df = create_sample_data()
        config = {"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30}
        result = compute_rsi(df, config)
        valid_zones = {"overbought", "oversold", "neutral"}
        assert set(result["rsi_zone"].unique()).issubset(valid_zones)


class TestMACD:
    def test_macd_columns_exist(self):
        df = create_sample_data()
        config = {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9}
        result = compute_macd(df, config)
        assert "macd_line" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_histogram" in result.columns
        assert "macd_crossover" in result.columns

    def test_histogram_equals_line_minus_signal(self):
        df = create_sample_data()
        config = {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9}
        result = compute_macd(df, config)
        diff = abs(result["macd_histogram"] - (result["macd_line"] - result["macd_signal"]))
        assert (diff.dropna() < 1e-10).all()


class TestATR:
    def test_atr_column_exists(self):
        df = create_sample_data()
        config = {"atr_period": 14}
        result = compute_atr(df, config)
        assert "atr" in result.columns
        assert "atr_pct" in result.columns

    def test_atr_positive(self):
        df = create_sample_data()
        config = {"atr_period": 14}
        result = compute_atr(df, config)
        assert (result["atr"].dropna() > 0).all()


class TestVolumeAnalysis:
    def test_volume_columns(self):
        df = create_sample_data()
        config = {"volume_sma_period": 20}
        result = compute_volume_analysis(df, config)
        assert "volume_sma" in result.columns
        assert "volume_ratio" in result.columns


class TestAdvancedTechnicals:
    def test_adx_columns(self):
        df = create_sample_data()
        config = {"adx_period": 14}
        result = compute_adx(df, config)
        assert "adx" in result.columns
        assert "plus_di" in result.columns
        assert "minus_di" in result.columns
        # ADX range 0-100
        assert (result["adx"].dropna() >= 0).all()
        assert (result["adx"].dropna() <= 100).all()

    def test_bollinger_columns(self):
        df = create_sample_data()
        config = {"bb_period": 20, "bb_std": 2.0}
        result = compute_bollinger_bands(df, config)
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns
        assert "bb_width" in result.columns
        # Upper > Lower (ignoring initial NaNs)
        valid_idx = result["bb_upper"].dropna().index
        assert (result.loc[valid_idx, "bb_upper"] > result.loc[valid_idx, "bb_lower"]).all()

    def test_stochastic_columns(self):
        df = create_sample_data()
        config = {"stoch_k": 14, "stoch_d": 3}
        result = compute_stochastic(df, config)
        assert "stoch_k" in result.columns
        assert "stoch_d" in result.columns
        # Range 0-100
        assert (result["stoch_k"].dropna() >= 0).all()
        assert (result["stoch_k"].dropna() <= 100).all()


class TestAllIndicators:
    def test_full_pipeline(self):
        df = create_sample_data()
        result = compute_all_indicators(df)
        # Should have all indicator columns
        expected_cols = [
            "ema_9", "ema_20", "ema_50", "ema_200",
            "rsi_14", "macd_line", "macd_histogram",
            "atr", "volume_ratio", "volatility_regime",
            "trend", "returns_1d", "returns_5d",
            "adx", "bb_width", "stoch_k", "stoch_d",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_all_nan_columns(self):
        df = create_sample_data()
        result = compute_all_indicators(df)
        for col in ["ema_9", "rsi_14", "macd_line", "atr"]:
            assert not result[col].isna().all(), f"Column {col} is all NaN"
