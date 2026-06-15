"""
Market Context Module
Fetches and processes broad market indices (Nifty 50, India VIX) to provide
contextual features for stock analysis.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict
from src.utils.logger import get_logger

logger = get_logger("stock_ai.data")


def get_market_features(period: str = "2y") -> pd.DataFrame:
    """
    Fetch and compute market context features (Nifty trend, VIX level).
    Returns a DataFrame indexed by Date with columns like:
    - market_trend_signal (1=Bullish, -1=Bearish)
    - market_above_ema50 (bool)
    - vix_level (float)
    - vix_regime (low/normal/high)
    """
    logger.info(f"Fetching market context data (Nifty 50 & VIX) for {period}...")
    
    # 1. Fetch Data
    tickers = "^NSEI ^INDIAVIX"
    data = yf.download(tickers, period=period, progress=False)
    
    if data.empty:
        logger.error("Failed to fetch market data")
        return pd.DataFrame()

    # Flatten MultiIndex columns if present
    if isinstance(data.columns, pd.MultiIndex):
        # Keep only Close prices
        df = data["Close"].copy()
    else:
        df = data.copy()

    # Rename columns for clarity
    # yfinance returns like: ^NSEI, ^INDIAVIX
    mapper = {
        "^NSEI": "nifty",
        "^INDIAVIX": "vix"
    }
    df = df.rename(columns=mapper)
    
    # Ensure we have both columns (handle download failures)
    if "nifty" not in df.columns or "vix" not in df.columns:
        logger.warning(f"Market data missing columns: {df.columns.tolist()}")
        return pd.DataFrame()

    # Forward fill missing data (e.g. holidays differ slightly or strict alignment)
    df = df.ffill()

    # 2. Compute Features
    
    # Nifty Trend
    df["nifty_ema_50"] = df["nifty"].ewm(span=50, adjust=False).mean()
    df["nifty_ema_200"] = df["nifty"].ewm(span=200, adjust=False).mean()
    
    df["nifty_above_ema50"] = (df["nifty"] > df["nifty_ema_50"]).astype(int)
    df["nifty_above_ema200"] = (df["nifty"] > df["nifty_ema_200"]).astype(int)
    
    # Nifty Returns (Momentum)
    df["nifty_return_1d"] = df["nifty"].pct_change()
    df["nifty_return_5d"] = df["nifty"].pct_change(5)
    
    # VIX Regimes
    # VIX < 12: Complacency (Low)
    # 12-20: Normal
    # 20-25: High Fear
    # > 25: Extreme Fear
    df["vix_level"] = df["vix"]
    df["vix_regime"] = 0  # Normal
    df.loc[df["vix"] < 12, "vix_regime"] = -1  # Low
    df.loc[df["vix"] > 20, "vix_regime"] = 1   # High
    df.loc[df["vix"] > 24, "vix_regime"] = 2   # Extreme

    # Composite Market Signal
    # 1 = Buy environment (Nifty > EMA50 and VIX < 24)
    # 0 = Caution
    # -1 = Sell environment (Nifty < EMA200 or VIX > 24)
    df["market_signal"] = 0
    
    bullish_cond = (df["nifty_above_ema50"] == 1) & (df["vix"] < 24)
    bearish_cond = (df["nifty"] < df["nifty_ema_200"]) | (df["vix"] > 24)
    
    df.loc[bullish_cond, "market_signal"] = 1
    df.loc[bearish_cond, "market_signal"] = -1
    
    # Select final features
    feature_cols = [
        "nifty_return_1d", "nifty_return_5d",
        "nifty_above_ema50", "nifty_above_ema200",
        "vix_level", "vix_regime", "market_signal"
    ]
    
    result = df[feature_cols].dropna()
    logger.info(f"Generated market features for {len(result)} days")
    
    return result
