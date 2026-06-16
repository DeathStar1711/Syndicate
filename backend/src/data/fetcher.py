"""
Data ingestion module — fetches real-time and recent OHLCV data from NSE/BSE via yfinance.
"""
import pandas as pd
import yfinance as yf
from typing import List, Optional, Dict
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from src.utils.logger import get_logger

logger = get_logger("stock_ai.data")


import datetime
from src.data.groww_mcp import get_historical_data_sync

def fetch_latest(ticker: str, period: str = "60d", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    Fetch recent OHLCV data for a single ticker.
    
    Args:
        ticker: Yahoo Finance ticker (e.g. 'RELIANCE.NS')
        period: Data period ('5d', '1mo', '3mo', '6mo', '1y', etc.)
        interval: Data interval ('1d', '1h', '15m', etc.)
    
    Returns:
        DataFrame with OHLCV columns or None on failure
    """
    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _do_fetch(t, p, i):
        end_date = datetime.date.today()
        # Parse simple periods like "1y", "60d", "5d", "6mo", etc.
        p_lower = p.lower()
        if 'y' in p_lower:
            days = int(p_lower.replace('y', '')) * 365
        elif 'mo' in p_lower:
            days = int(p_lower.replace('mo', '')) * 30
        elif 'd' in p_lower:
            days = int(p_lower.replace('d', ''))
        else:
            days = 60
        start_date = end_date - datetime.timedelta(days=days)
        
        # Groww interval in minutes
        interval_mins = "1440"
        if i == "1h":
            interval_mins = "60"
        elif i == "15m":
            interval_mins = "15"
            
        df = get_historical_data_sync(
            ticker=t,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            interval=interval_mins
        )
        
        if df is None or df.empty:
            logger.warning(f"Groww MCP returned empty data for {t}. Falling back to yfinance.")
            stock = yf.Ticker(t)
            yf_period = p
            if 'mo' in p.lower():
                yf_period = p.replace('mo', 'mo') # same
            df = stock.history(period=yf_period, interval=i)
            
        if df is None or df.empty:
            raise ValueError(f"No data returned for {t}")
            
        # Clean column names to lowercase
        df.columns = [col.lower() for col in df.columns]
        return df

    try:
        df = _do_fetch(ticker, period, interval)
        
        # We don't need to rename columns, they are handled in groww_mcp.py
        # but let's ensure standard format open, high, low, close, volume
        # We don't need to rename columns, they are handled in yfinance
        df = df[["open", "high", "low", "close", "volume"]].copy()
        
        logger.info(f"Fetched {len(df)} rows for {ticker} (period={period})")
        return df
    
    except Exception as e:
        logger.error(f"Error fetching historical data for {ticker}: {e}")
        return None


def fetch_batch(tickers: List[str], period: str = "60d", interval: str = "1d") -> Dict[str, pd.DataFrame]:
    """
    Fetch data for multiple tickers.
    
    Args:
        tickers: List of Yahoo Finance tickers
        period: Data period
        interval: Data interval
    
    Returns:
        Dictionary mapping ticker -> DataFrame
    """
    results = {}
    failed = []
    
    logger.info(f"Fetching batch data for {len(tickers)} tickers...")
    
    for ticker in tickers:
        df = fetch_latest(ticker, period=period, interval=interval)
        if df is not None and not df.empty:
            results[ticker] = df
        else:
            failed.append(ticker)
    
    if failed:
        logger.warning(f"Failed to fetch data for: {', '.join(failed)}")
    
    logger.info(f"Successfully fetched {len(results)}/{len(tickers)} tickers")
    return results


def fetch_index(symbol: str = "^NSEI", period: str = "60d") -> Optional[pd.DataFrame]:
    """
    Fetch index data for benchmarking.
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        
        # Format period correctly for yf (e.g. 3y)
        yf_period = period.lower().replace("d", "d").replace("mo", "mo").replace("y", "y")
        if "y" not in yf_period and "mo" not in yf_period and "d" not in yf_period:
            yf_period = "60d" # fallback
            
        df = stock.history(period=yf_period, interval="1d")
        if df is None or df.empty:
            logger.warning(f"No index data fetched for {symbol}")
            return None
            
        df.columns = [col.lower() for col in df.columns]
        # Strip timezone if present
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            
        return df
    except Exception as e:
        logger.error(f"Error fetching index {symbol}: {e}")
        return None


def get_current_price(ticker: str, use_live_api: bool = False) -> Optional[float]:
    """
    Get the most recent closing or live traded price for a ticker.
    First attempts Groww API for sub-second LTP, falls back to yfinance.
    
    Args:
        ticker: Yahoo Finance ticker
        use_live_api: Boolean to try Groww API first
    
    Returns:
        Latest price or None
    """
    if use_live_api:
        from src.data.groww_mcp import get_live_prices_sync
        try:
            prices = get_live_prices_sync([ticker])
            if ticker in prices:
                return prices[ticker]
        except Exception as e:
            logger.warning(f"Groww MCP live price failed for {ticker}, falling back to yfinance: {e}")

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _do_get(t):
        stock = yf.Ticker(t)
        df = stock.history(period="5d")
        if df.empty:
            raise ValueError(f"No pricing data for {t}")
        return float(df["Close"].iloc[-1])

    try:
        return _do_get(ticker)
    except Exception as e:
        logger.error(f"Error getting current price for {ticker}: {e}")
        return None


def get_current_prices(tickers: List[str], use_live_api: bool = False) -> Dict[str, float]:
    """
    Get current prices for multiple tickers.
    
    Args:
        tickers: List of Yahoo Finance tickers
        use_live_api: Boolean to try Groww API first
    
    Returns:
        Dictionary mapping ticker -> latest price
    """
    prices = {}
    if use_live_api:
        from src.data.groww_mcp import get_live_prices_sync
        try:
            mcp_prices = get_live_prices_sync(tickers)
            prices.update(mcp_prices)
        except Exception as e:
            logger.warning(f"Groww MCP batch live price failed, falling back: {e}")
            
    # For any missing tickers, fallback to single fetch (which falls back to yfinance)
    for ticker in tickers:
        if ticker not in prices:
            price = get_current_price(ticker, use_live_api=False)
            if price is not None:
                prices[ticker] = price
    return prices
