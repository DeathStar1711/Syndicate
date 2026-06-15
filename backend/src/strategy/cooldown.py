"""
Ticker cooldown tracker.
Prevents the same stock from being recommended too frequently.
Uses a JSON file to persist recommendation history.
"""
import os
import json
from datetime import datetime, timedelta
from typing import Set, Optional
from filelock import FileLock
from src.utils.helpers import get_data_dir, now_ist
from src.utils.logger import get_logger

logger = get_logger("stock_ai.strategy")

COOLDOWN_FILE = "ticker_cooldown.json"

# Default cooldown periods (days)
INTRADAY_COOLDOWN = 3
SWING_COOLDOWN = 14


def _get_filepath() -> str:
    return os.path.join(get_data_dir(), COOLDOWN_FILE)


def _get_lockpath() -> str:
    return _get_filepath() + ".lock"


def _load() -> dict:
    """Load cooldown data from file."""
    filepath = _get_filepath()
    if not os.path.exists(filepath):
        return {"recommendations": []}
    try:
        lock = FileLock(_get_lockpath(), timeout=10)
        with lock:
            with open(filepath, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError, TimeoutError):
        return {"recommendations": []}


def _save(data: dict) -> None:
    """Save cooldown data to file."""
    filepath = _get_filepath()
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        lock = FileLock(_get_lockpath(), timeout=10)
        with lock:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
    except TimeoutError:
        logger.error("Failed to acquire lock to save cooldown data.")


def record_recommendation(ticker: str, trade_type: str = "intraday") -> None:
    """
    Mark a ticker as recommended today.

    Args:
        ticker: Stock ticker symbol
        trade_type: 'intraday', 'swing', or 'breakout'
    """
    data = _load()
    if "recommendations" not in data:
        data["recommendations"] = []
    
    data["recommendations"].append({
        "ticker": ticker,
        "trade_type": trade_type,
        "date": now_ist().strftime("%Y-%m-%d"),
    })
    _save(data)
    logger.debug(f"Cooldown recorded: {ticker} ({trade_type})")


def record_batch(tickers: list, trade_type: str = "intraday") -> None:
    """Record multiple tickers at once."""
    data = _load()
    if "recommendations" not in data:
        data["recommendations"] = []
        
    today = now_ist().strftime("%Y-%m-%d")
    for ticker in tickers:
        data["recommendations"].append({
            "ticker": ticker,
            "trade_type": trade_type,
            "date": today,
        })
    _save(data)
    if tickers:
        logger.info(f"Cooldown recorded {len(tickers)} {trade_type} tickers")


def get_cooled_tickers(
    trade_type: Optional[str] = None,
    cooldown_days: Optional[int] = None,
) -> Set[str]:
    """
    Get tickers that are still in their cooldown period.

    Args:
        trade_type: Filter by type ('intraday', 'swing', 'breakout').
                    If None, uses default cooldown for each type.
        cooldown_days: Override cooldown period. If None, uses defaults.

    Returns:
        Set of ticker symbols still on cooldown
    """
    data = _load()
    now = now_ist()
    cooled = set()

    for rec in data.get("recommendations", []):
        rec_date = datetime.strptime(rec["date"], "%Y-%m-%d")
        rec_type = rec.get("trade_type", "intraday")

        # Determine cooldown
        if cooldown_days is not None:
            cd = cooldown_days
        elif rec_type == "swing":
            cd = SWING_COOLDOWN
        else:
            cd = INTRADAY_COOLDOWN

        # Filter by trade_type if specified
        if trade_type and rec_type != trade_type:
            continue

        if (now.replace(tzinfo=None) - rec_date).days < cd:
            cooled.add(rec["ticker"])

    return cooled


def cleanup_old_entries(max_age_days: int = 30) -> int:
    """
    Remove entries older than max_age_days.

    Returns:
        Number of entries removed
    """
    data = _load()
    cutoff = now_ist() - timedelta(days=max_age_days)
    original = len(data.get("recommendations", []))

    data["recommendations"] = [
        r for r in data.get("recommendations", [])
        if datetime.strptime(r["date"], "%Y-%m-%d") >= cutoff.replace(tzinfo=None)
    ]

    removed = original - len(data["recommendations"])
    if removed > 0:
        _save(data)
        logger.info(f"Cooldown cleanup: removed {removed} old entries")
    return removed
