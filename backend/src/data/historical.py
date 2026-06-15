"""
Historical data downloader — downloads and caches 3-5 years of OHLCV data for backtesting and ML training.
"""
import os
import pandas as pd
import yfinance as yf
from typing import List, Optional
from datetime import datetime, timedelta
from src.utils.logger import get_logger
from src.utils.helpers import get_data_dir

logger = get_logger("stock_ai.data")


def download_historical(
    tickers: List[str],
    years: int = 5,
    output_dir: Optional[str] = None,
    force: bool = False
) -> dict:
    """
    Download historical OHLCV data and save to CSV files.
    
    Args:
        tickers: List of Yahoo Finance tickers
        years: Number of years of history to download
        output_dir: Directory to save CSVs (default: data/historical/)
        force: If True, re-download even if file exists
    
    Returns:
        Dictionary of ticker -> file path for successfully downloaded data
    """
    if output_dir is None:
        output_dir = os.path.join(get_data_dir(), "historical")
    os.makedirs(output_dir, exist_ok=True)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365)
    
    downloaded = {}
    failed = []

    logger.info(f"Downloading {years}-year historical data for {len(tickers)} tickers...")
    logger.info(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

    for ticker in tickers:
        filename = f"{ticker.replace('.', '_')}.csv"
        filepath = os.path.join(output_dir, filename)

        # Skip if already downloaded (unless force=True)
        if os.path.exists(filepath) and not force:
            # Check if file is recent (less than 1 day old)
            file_age = datetime.now().timestamp() - os.path.getmtime(filepath)
            if file_age < 86400:  # 24 hours
                logger.info(f"Skipping {ticker} — recent data exists: {filepath}")
                downloaded[ticker] = filepath
                continue

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d"
            )

            if df.empty:
                logger.warning(f"No historical data for {ticker}")
                failed.append(ticker)
                continue

            # Clean up
            df.index.name = "Date"
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.columns = ["open", "high", "low", "close", "volume"]
            df["ticker"] = ticker

            # Save
            df.to_csv(filepath)
            downloaded[ticker] = filepath
            logger.info(f"Downloaded {len(df)} days for {ticker} -> {filepath}")

        except Exception as e:
            logger.error(f"Error downloading {ticker}: {e}")
            failed.append(ticker)

    logger.info(f"Download complete: {len(downloaded)}/{len(tickers)} successful")
    if failed:
        logger.warning(f"Failed tickers: {', '.join(failed)}")

    return downloaded


def load_historical(ticker: str, data_dir: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Load historical data from CSV for a ticker.
    
    Args:
        ticker: Yahoo Finance ticker
        data_dir: Directory where CSVs are stored
    
    Returns:
        DataFrame with historical data or None
    """
    if data_dir is None:
        data_dir = os.path.join(get_data_dir(), "historical")

    filename = f"{ticker.replace('.', '_')}.csv"
    filepath = os.path.join(data_dir, filename)

    if not os.path.exists(filepath):
        logger.warning(f"No historical data file found for {ticker}: {filepath}")
        return None

    try:
        df = pd.read_csv(filepath, index_col="Date", parse_dates=True)
        logger.info(f"Loaded {len(df)} rows of historical data for {ticker}")
        return df
    except Exception as e:
        logger.error(f"Error loading historical data for {ticker}: {e}")
        return None


def load_all_historical(tickers: List[str], data_dir: Optional[str] = None) -> dict:
    """
    Load historical data for all specified tickers.
    
    Returns:
        Dictionary of ticker -> DataFrame
    """
    results = {}
    for ticker in tickers:
        df = load_historical(ticker, data_dir)
        if df is not None:
            results[ticker] = df
    return results
