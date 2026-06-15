"""
Test suite for backtesting metrics.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.metrics import calculate_metrics, _calculate_max_drawdown
import pandas as pd


class TestMetrics:
    def test_empty_trades(self):
        metrics = calculate_metrics([], starting_capital=100000)
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0

    def test_all_winners(self):
        trades = [
            {"pnl": 1000, "pnl_pct": 2.0, "entry_date": "2024-01-01", "exit_date": "2024-01-05"},
            {"pnl": 500, "pnl_pct": 1.0, "entry_date": "2024-01-06", "exit_date": "2024-01-10"},
        ]
        metrics = calculate_metrics(trades, starting_capital=100000)
        assert metrics["win_rate"] == 100.0
        assert metrics["total_pnl"] == 1500
        assert metrics["profit_factor"] > 0  # No losses, so profit factor is large

    def test_all_losers(self):
        trades = [
            {"pnl": -500, "pnl_pct": -1.0, "entry_date": "2024-01-01", "exit_date": "2024-01-05"},
            {"pnl": -300, "pnl_pct": -0.6, "entry_date": "2024-01-06", "exit_date": "2024-01-10"},
        ]
        metrics = calculate_metrics(trades, starting_capital=100000)
        assert metrics["win_rate"] == 0.0
        assert metrics["total_pnl"] == -800

    def test_mixed_trades(self):
        trades = [
            {"pnl": 2000, "pnl_pct": 4.0, "entry_date": "2024-01-01", "exit_date": "2024-01-05"},
            {"pnl": -500, "pnl_pct": -1.0, "entry_date": "2024-01-06", "exit_date": "2024-01-10"},
            {"pnl": 1000, "pnl_pct": 2.0, "entry_date": "2024-01-11", "exit_date": "2024-01-15"},
            {"pnl": -300, "pnl_pct": -0.6, "entry_date": "2024-01-16", "exit_date": "2024-01-20"},
        ]
        metrics = calculate_metrics(trades, starting_capital=100000)
        assert metrics["total_trades"] == 4
        assert metrics["win_count"] == 2
        assert metrics["loss_count"] == 2
        assert metrics["win_rate"] == 50.0
        assert metrics["total_pnl"] == 2200
        assert metrics["profit_factor"] > 1

    def test_max_drawdown(self):
        equity = pd.Series([100000, 105000, 103000, 108000, 101000, 110000])
        dd = _calculate_max_drawdown(equity)
        # Max drawdown should be from 108000 to 101000 = 6.48%
        assert dd > 6.0
        assert dd < 7.0
