"""Tests for the ticker cooldown module."""
import os
import json
import pytest
import tempfile
from unittest.mock import patch
from datetime import datetime, timedelta


# Mock the data dir before importing cooldown
@pytest.fixture(autouse=True)
def mock_data_dir(tmp_path):
    """Use a temp directory for cooldown data."""
    with patch("src.strategy.cooldown.get_data_dir", return_value=str(tmp_path)):
        # Clear any cached data
        filepath = os.path.join(str(tmp_path), "ticker_cooldown.json")
        if os.path.exists(filepath):
            os.remove(filepath)
        yield tmp_path


from src.strategy.cooldown import (
    record_recommendation,
    record_batch,
    get_cooled_tickers,
    cleanup_old_entries,
    _load,
    _save,
    _get_filepath,
    INTRADAY_COOLDOWN,
    SWING_COOLDOWN,
)


class TestCooldownRecord:
    """Test recording recommendations."""

    def test_record_single(self, mock_data_dir):
        record_recommendation("RELIANCE.NS", "intraday")
        data = _load()
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["ticker"] == "RELIANCE.NS"
        assert data["recommendations"][0]["trade_type"] == "intraday"

    def test_record_batch(self, mock_data_dir):
        tickers = ["TCS.NS", "INFY.NS", "HDFCBANK.NS"]
        record_batch(tickers, "swing")
        data = _load()
        assert len(data["recommendations"]) == 3
        assert all(r["trade_type"] == "swing" for r in data["recommendations"])

    def test_record_preserves_existing(self, mock_data_dir):
        record_recommendation("A.NS")
        record_recommendation("B.NS")
        data = _load()
        assert len(data["recommendations"]) == 2


class TestCooldownFilter:
    """Test filtering cooled tickers."""

    def test_recently_recorded_is_cooled(self, mock_data_dir):
        record_recommendation("RELIANCE.NS", "intraday")
        cooled = get_cooled_tickers()
        assert "RELIANCE.NS" in cooled

    def test_old_entry_not_cooled(self, mock_data_dir):
        # Manually insert old entry
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        _save({"recommendations": [
            {"ticker": "OLD.NS", "trade_type": "intraday", "date": old_date}
        ]})
        cooled = get_cooled_tickers()
        assert "OLD.NS" not in cooled  # Past 3-day intraday cooldown

    def test_swing_cooldown_longer(self, mock_data_dir):
        # Swings have 14-day cooldown vs 3-day for intraday
        day_5 = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        _save({"recommendations": [
            {"ticker": "SWING.NS", "trade_type": "swing", "date": day_5},
            {"ticker": "INTRA.NS", "trade_type": "intraday", "date": day_5},
        ]})
        cooled = get_cooled_tickers()
        assert "SWING.NS" in cooled       # Still within 14-day cooldown
        assert "INTRA.NS" not in cooled    # Past 3-day cooldown

    def test_filter_by_trade_type(self, mock_data_dir):
        record_recommendation("A.NS", "intraday")
        record_recommendation("B.NS", "swing")
        cooled_intraday = get_cooled_tickers(trade_type="intraday")
        assert "A.NS" in cooled_intraday
        assert "B.NS" not in cooled_intraday

    def test_empty_file_returns_empty(self, mock_data_dir):
        cooled = get_cooled_tickers()
        assert cooled == set()


class TestCooldownCleanup:
    """Test cleanup of old entries."""

    def test_cleanup_removes_old(self, mock_data_dir):
        old = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
        recent = datetime.now().strftime("%Y-%m-%d")
        _save({"recommendations": [
            {"ticker": "OLD.NS", "trade_type": "intraday", "date": old},
            {"ticker": "NEW.NS", "trade_type": "intraday", "date": recent},
        ]})
        removed = cleanup_old_entries(max_age_days=30)
        assert removed == 1
        data = _load()
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["ticker"] == "NEW.NS"

    def test_cleanup_nothing_to_remove(self, mock_data_dir):
        record_recommendation("FRESH.NS")
        removed = cleanup_old_entries(max_age_days=30)
        assert removed == 0
