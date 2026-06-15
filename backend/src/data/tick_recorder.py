"""
Records live WebSocket ticks and order book imbalance into a local SQLite database
for training the future Intraday ML Model.
"""
import sqlite3
import os
import json
from datetime import datetime
from src.utils.logger import get_logger

logger = get_logger("stock_ai.data.recorder")


class TickRecorder:
    def __init__(self, db_path: str = "data/tick_data.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database schema for tick data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    ltp REAL NOT NULL,
                    volume INTEGER,
                    vwap REAL,
                    best_bid REAL,
                    best_ask REAL,
                    imbalance_ratio REAL,
                    raw_depth TEXT
                )
            ''')
            # Index for fast querying by ticker and time
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ticker_time ON ticks (ticker, timestamp)')
            conn.commit()

    def record_tick(self, tick_data: dict):
        """
        Record a single tick event into the database.
        Expected keys in tick_data: ticker, ltp, volume, vwap, best_bid, best_ask, imbalance_ratio, raw_depth
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO ticks 
                    (ticker, timestamp, ltp, volume, vwap, best_bid, best_ask, imbalance_ratio, raw_depth)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    tick_data.get("ticker"),
                    datetime.now().isoformat(),
                    tick_data.get("ltp", 0.0),
                    tick_data.get("volume", 0),
                    tick_data.get("vwap", 0.0),
                    tick_data.get("best_bid", 0.0),
                    tick_data.get("best_ask", 0.0),
                    tick_data.get("imbalance_ratio", 0.0),
                    json.dumps(tick_data.get("raw_depth", {}))
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to record tick for {tick_data.get('ticker')}: {e}")

