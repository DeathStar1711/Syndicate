"""
Technical indicator computation module.
Computes EMA, RSI, MACD, ATR, volume analysis, and volatility regime detection.
"""
import pandas as pd
import numpy as np
from typing import Optional
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.features")


def compute_all_indicators(df: pd.DataFrame, config: Optional[dict] = None, 
                           oi_data: Optional[dict] = None, index_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Compute all technical indicators on the given OHLCV DataFrame.
    
    Args:
        df: DataFrame with columns [open, high, low, close, volume]
        config: Strategy config dict (uses defaults if None)
        oi_data: Open Interest analysis from Groww MCP
        index_df: DataFrame with Sector/Index OHLCV data for benchmarking
    
    Returns:
        DataFrame with all indicator columns added
    """
    if config is None:
        config = load_config().get("strategy", {})
    
    df = df.copy()
    
    # EMAs
    df = compute_emas(df, config)
    
    # RSI
    df = compute_rsi(df, config)
    
    # MACD
    df = compute_macd(df, config)
    
    # ATR
    df = compute_atr(df, config)
    
    # Volume analysis
    df = compute_volume_analysis(df, config)
    
    # Volatility regime
    df = compute_volatility_regime(df, config)

    # Advanced Technicals (ADX, Bollinger, Stoch)
    df = compute_adx(df, config)
    df = compute_bollinger_bands(df, config)
    df = compute_stochastic(df, config)
    df = compute_support_resistance(df, config)
    df = compute_candlestick_patterns(df, config)
    
    # Market Microstructure & Derivatives
    df = compute_derivatives(df, oi_data)
    df = compute_relative_strength(df, index_df)
    
    # Advanced Derived Features (VWAP, HV, VPT)
    df = compute_advanced_technicals(df)
    
    # Seasonality Features
    df = compute_seasonality(df)
    
    # Derived signals
    df = compute_derived_signals(df, config)
    
    return df

def compute_seasonality(df: pd.DataFrame) -> pd.DataFrame:
    """Compute time-based seasonality features."""
    # Ensure index is datetime
    idx = pd.to_datetime(df.index)
    df["day_of_week"] = idx.dayofweek
    df["is_month_end"] = idx.is_month_end.astype(int)
    return df

def compute_advanced_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute VWAP Distance, Historical Volatility, and Volume Price Trend."""
    # 1. Rolling VWAP (10-day)
    # Typical price = (H+L+C)/3
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]
    roll_vol = df["volume"].rolling(window=10).sum()
    roll_tp_vol = tp_vol.rolling(window=10).sum()
    vwap_10d = roll_tp_vol / roll_vol
    df["vwap_distance_10d"] = (df["close"] - vwap_10d) / vwap_10d
    
    # 2. Historical Volatility (20-day annualized std of log returns)
    log_returns = np.log(df["close"] / df["close"].shift(1))
    # 252 trading days in a year
    df["hist_volatility_20d"] = log_returns.rolling(window=20).std() * np.sqrt(252)
    
    # 3. Volume Price Trend (VPT) and 5-day slope
    # VPT = Previous VPT + Volume * (Close - Prev Close) / Prev Close
    pct_change = df["close"].pct_change()
    vpt = (df["volume"] * pct_change).cumsum()
    # Slope over 5 days (rate of change of VPT)
    df["vpt_slope_5d"] = vpt.diff(5) / vpt.abs().rolling(5).mean().replace(0, np.nan)
    df["vpt_slope_5d"] = df["vpt_slope_5d"].fillna(0)
    
    return df

def compute_derivatives(df: pd.DataFrame, oi_data: Optional[dict]) -> pd.DataFrame:
    """Compute Open Interest and PCR features."""
    if oi_data and "pcr" in oi_data:
        df["pcr"] = float(oi_data["pcr"])
        # Calculate OI change percentage if available
        call_oi_change = float(oi_data.get("call_oi_change", 0))
        put_oi_change = float(oi_data.get("put_oi_change", 0))
        total_oi = float(oi_data.get("total_call_oi", 1)) + float(oi_data.get("total_put_oi", 1))
        df["oi_change_pct"] = ((call_oi_change + put_oi_change) / total_oi) * 100 if total_oi > 0 else 0.0
    else:
        # Default neutral values for non-F&O stocks
        df["pcr"] = 1.0
        df["oi_change_pct"] = 0.0
    return df

def compute_relative_strength(df: pd.DataFrame, index_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Compute Relative Strength against the benchmark index."""
    if index_df is not None and not index_df.empty:
        # Align index dates with stock dates
        # Use close price for returns
        idx_close = index_df["close"]
        
        # Calculate returns
        stock_returns_1d = df["close"].pct_change(1)
        index_returns_1d = idx_close.pct_change(1)
        df["rs_vs_index_1d"] = stock_returns_1d - index_returns_1d
        
        stock_returns_5d = df["close"].pct_change(5)
        index_returns_5d = idx_close.pct_change(5)
        df["rs_vs_index_5d"] = stock_returns_5d - index_returns_5d
    else:
        df["rs_vs_index_1d"] = 0.0
        df["rs_vs_index_5d"] = 0.0
        
    return df


def compute_emas(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute Exponential Moving Averages (9, 20, 50, 200)."""
    periods = {
        "ema_9": config.get("ema_fast", 9),
        "ema_20": config.get("ema_medium", 20),
        "ema_50": config.get("ema_slow", 50),
        "ema_200": config.get("ema_trend", 200),
    }
    
    for col_name, period in periods.items():
        df[col_name] = df["close"].ewm(span=period, adjust=False).mean()
        # EMA slope (rate of change over 3 periods)
        df[f"{col_name}_slope"] = df[col_name].pct_change(3) * 100
    
    return df


def compute_rsi(df: pd.DataFrame, config: dict, period: Optional[int] = None) -> pd.DataFrame:
    """Compute Relative Strength Index."""
    period = period or config.get("rsi_period", 14)
    
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    
    # RSI zones
    overbought = config.get("rsi_overbought", 70)
    oversold = config.get("rsi_oversold", 30)
    df["rsi_zone"] = "neutral"
    df.loc[df["rsi_14"] >= overbought, "rsi_zone"] = "overbought"
    df.loc[df["rsi_14"] <= oversold, "rsi_zone"] = "oversold"
    
    return df


def compute_macd(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute MACD, Signal Line, and Histogram."""
    fast = config.get("macd_fast", 12)
    slow = config.get("macd_slow", 26)
    signal_period = config.get("macd_signal", 9)
    
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    
    df["macd_line"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd_line"].ewm(span=signal_period, adjust=False).mean()
    df["macd_histogram"] = df["macd_line"] - df["macd_signal"]
    
    # MACD crossover signals
    df["macd_crossover"] = 0
    df.loc[
        (df["macd_line"] > df["macd_signal"]) & 
        (df["macd_line"].shift(1) <= df["macd_signal"].shift(1)),
        "macd_crossover"
    ] = 1  # Bullish crossover
    df.loc[
        (df["macd_line"] < df["macd_signal"]) & 
        (df["macd_line"].shift(1) >= df["macd_signal"].shift(1)),
        "macd_crossover"
    ] = -1  # Bearish crossover
    
    return df


def compute_atr(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute Average True Range."""
    period = config.get("atr_period", 14)
    
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(window=period).mean()
    
    # ATR as percentage of price
    df["atr_pct"] = (df["atr"] / df["close"]) * 100
    
    return df


def compute_volume_analysis(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute volume SMA and volume ratio."""
    sma_period = config.get("volume_sma_period", 20)
    
    df["volume_sma"] = df["volume"].rolling(window=sma_period).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma"].replace(0, np.nan)
    
    # Volume trend (increasing/decreasing over 5 days)
    df["volume_trend"] = df["volume"].rolling(5).apply(
        lambda x: 1 if x.iloc[-1] > x.iloc[0] else -1, raw=False
    )
    
    return df


def compute_volatility_regime(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Detect volatility regime based on ATR percentile.
    Regimes: low, normal, high, extreme
    """
    low_threshold = config.get("volatility_low", 25)
    high_threshold = config.get("volatility_high", 75)
    extreme_threshold = config.get("volatility_extreme", 90)
    
    # Rolling ATR percentile (over ~6 months / 126 trading days)
    df["atr_percentile"] = df["atr_pct"].rolling(126, min_periods=20).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100, raw=False
    )
    
    df["volatility_regime"] = "normal"
    df.loc[df["atr_percentile"] <= low_threshold, "volatility_regime"] = "low"
    df.loc[df["atr_percentile"] >= high_threshold, "volatility_regime"] = "high"
    df.loc[df["atr_percentile"] >= extreme_threshold, "volatility_regime"] = "extreme"
    
    return df


def compute_adx(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute Average Directional Index (ADX)."""
    period = config.get("adx_period", 14)
    
    df = df.copy()
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # Smoothed TR and DM (Wilder's smoothing)
    # Typically alpha = 1/period. Pandas ewm uses com or span.
    # Wilder's smoothing is equivalent to EMA with alpha=1/n.
    # We can use ewm(alpha=1/period, adjust=False)
    # Smoothed TR and DM (Wilder's smoothing)
    # Typically alpha = 1/period. Pandas ewm uses com or span.
    # Wilder's smoothing is equivalent to EMA with alpha=1/n.
    # We can use ewm(alpha=1/period, adjust=False)
    # IMPORTANT: We must bfill() first because adjust=False propagates initial NaNs indefinitely!
    # IMPORTANT: plus_dm is np.array, must attach index to align with tr_smooth!
    
    tr_smooth = pd.Series(tr).bfill().ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).bfill().ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).bfill().ewm(alpha=1/period, adjust=False).mean()
    
    # DI (+DI and -DI)
    plus_di = 100 * (plus_dm_smooth / tr_smooth)
    minus_di = 100 * (minus_dm_smooth / tr_smooth)
    
    # DX
    sum_di = plus_di + minus_di
    dx = 100 * np.abs(plus_di - minus_di) / (sum_di + 1e-9)
    
    # ADX
    df["adx"] = dx.bfill().ewm(alpha=1/period, adjust=False).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    
    return df


def compute_bollinger_bands(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute Bollinger Bands and Bandwidth."""
    period = config.get("bb_period", 20)
    std_dev = config.get("bb_std", 2.0)
    
    sma = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    
    df["bb_upper"] = sma + (std * std_dev)
    df["bb_lower"] = sma - (std * std_dev)
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma * 100  # Bandwidth %
    
    # Squeeze indicator (Bandwidth low percentile)
    # Computed relative to recent history if needed, but raw width is useful feature
    
    return df


def compute_stochastic(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute Stochastic Oscillator (K and D)."""
    k_period = config.get("stoch_k", 14)
    d_period = config.get("stoch_d", 3)
    
    # Use rolling min/max
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    
    # %K
    df["stoch_k"] = 100 * ((df["close"] - low_min) / (high_max - low_min))
    
    # %D (SMA of %K)
    df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
    
    return df


def compute_support_resistance(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute proximity to dynamic support and resistance levels."""
    window = config.get("sr_window", 20)
    
    # Rolling min and max act as dynamic support and resistance
    df["rolling_high"] = df["high"].rolling(window=window).max()
    df["rolling_low"] = df["low"].rolling(window=window).min()
    
    # Proximity to Support/Resistance (0 to 1)
    # 0 = at support, 1 = at resistance
    df["sr_proximity"] = (df["close"] - df["rolling_low"]) / (df["rolling_high"] - df["rolling_low"] + 1e-9)
    
    return df

def compute_candlestick_patterns(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Detect basic candlestick patterns (Doji, Engulfing)."""
    # Doji: Open and Close are very close (body < 10% of total range)
    body = (df["close"] - df["open"]).abs()
    rng = df["high"] - df["low"]
    df["is_doji"] = (body <= 0.1 * rng).astype(int)
    
    # Bullish Engulfing: Previous red candle completely engulfed by current green candle
    prev_red = df["close"].shift(1) < df["open"].shift(1)
    curr_green = df["close"] > df["open"]
    engulfs_body = (df["close"] > df["open"].shift(1)) & (df["open"] < df["close"].shift(1))
    
    df["bullish_engulfing"] = (prev_red & curr_green & engulfs_body).astype(int)
    
    # Bearish Engulfing
    prev_green = df["close"].shift(1) > df["open"].shift(1)
    curr_red = df["close"] < df["open"]
    engulfs_body_bear = (df["close"] < df["open"].shift(1)) & (df["open"] > df["close"].shift(1))
    
    df["bearish_engulfing"] = (prev_green & curr_red & engulfs_body_bear).astype(int)
    
    return df

def compute_derived_signals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute derived / composite signals from base indicators."""
    # Trend direction based on EMA alignment
    df["trend"] = "sideways"
    
    bullish_mask = (
        (df["close"] > df["ema_20"]) &
        (df["ema_9"] > df["ema_20"]) &
        (df["ema_20"] > df["ema_50"])
    )
    bearish_mask = (
        (df["close"] < df["ema_20"]) &
        (df["ema_9"] < df["ema_20"]) &
        (df["ema_20"] < df["ema_50"])
    )
    
    df.loc[bullish_mask, "trend"] = "bullish"
    df.loc[bearish_mask, "trend"] = "bearish"
    
    # Strong trend: price above/below EMA 200
    df["strong_trend"] = "neutral"
    df.loc[df["close"] > df["ema_200"], "strong_trend"] = "bullish"
    df.loc[df["close"] < df["ema_200"], "strong_trend"] = "bearish"
    
    # Returns
    df["returns_1d"] = df["close"].pct_change(1)
    df["returns_5d"] = df["close"].pct_change(5)
    df["returns_20d"] = df["close"].pct_change(20)
    
    return df
