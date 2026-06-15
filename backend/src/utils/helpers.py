"""
Common utility functions used across the project.
"""
import os
import yaml
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from src.utils.config_schema import AppConfigSchema


# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))


def load_config(config_path: str = "config/config.yaml") -> dict:
    """Load and return the main configuration dictionary."""
    # Try project root first, then relative paths
    if not os.path.isabs(config_path):
        project_root = get_project_root()
        config_path = os.path.join(project_root, config_path)
    
    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)
    
    # Validate configuration
    try:
        validated_config = AppConfigSchema(**config_data)
        # Return as dict for compatibility with existing code
        return validated_config.model_dump()
    except Exception as e:
        print(f"Error validating config: {e}")
        raise ValueError(f"Invalid configuration in {config_path}:\n{e}")


def load_watchlist(watchlist_path: str = "config/watchlist.yaml") -> dict:
    """Load and return the stock watchlist configuration."""
    if not os.path.isabs(watchlist_path):
        project_root = get_project_root()
        watchlist_path = os.path.join(project_root, watchlist_path)
    
    with open(watchlist_path, "r") as f:
        return yaml.safe_load(f)


def get_tickers(watchlist_path: str = "config/watchlist.yaml") -> list:
    """Get list of ticker symbols from watchlist."""
    watchlist = load_watchlist(watchlist_path)
    return [stock["ticker"] for stock in watchlist.get("stocks", [])]


def get_project_root() -> str:
    """Get the project root directory (where config/ folder lives)."""
    # Walk up from this file to find the project root
    current = os.path.dirname(os.path.abspath(__file__))
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, "config", "config.yaml")):
            return current
        current = os.path.dirname(current)
    # Fallback to current working directory
    return os.getcwd()


def get_data_dir() -> str:
    """Get the data directory path, creating it if necessary."""
    data_dir = os.path.join(get_project_root(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def now_ist() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def is_market_hours() -> bool:
    """Check if current time is within NSE market hours (9:15 AM - 3:30 PM IST, weekdays)."""
    current = now_ist()
    # Weekday check (Mon=0, Sun=6)
    if current.weekday() >= 5:
        return False
    market_open = current.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = current.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= current <= market_close


def ensure_dirs():
    """Create all required data directories."""
    project_root = get_project_root()
    dirs = [
        "data/historical",
        "data/models",
        "data/trades",
        "data/reports",
        "data/logs",
    ]
    for d in dirs:
        os.makedirs(os.path.join(project_root, d), exist_ok=True)


def format_inr(amount: float) -> str:
    """Format a number as Indian Rupees."""
    if abs(amount) >= 10_000_000:
        return f"₹{amount / 10_000_000:.2f} Cr"
    elif abs(amount) >= 100_000:
        return f"₹{amount / 100_000:.2f} L"
    else:
        return f"₹{amount:,.2f}"


def load_env():
    """Load environment variables from .env file."""
    project_root = get_project_root()
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
