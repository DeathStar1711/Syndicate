"""
Test suite for position sizing and risk management.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.position_sizing import (
    calculate_position_size,
    calculate_stop_loss,
    calculate_target,
    calculate_risk_reward,
)


class TestPositionSizing:
    def test_basic_position_size(self):
        result = calculate_position_size(
            capital=100000,
            entry_price=1000,
            stop_loss=950,
            max_risk_pct=0.02,
            max_position_pct=0.20,
        )
        assert result["shares"] > 0
        assert result["risk_amount"] <= 100000 * 0.02
        assert result["position_value"] <= 100000 * 0.20

    def test_risk_constraint(self):
        """Position should be limited by 2% risk rule."""
        result = calculate_position_size(
            capital=100000,
            entry_price=500,
            stop_loss=480,
            max_risk_pct=0.02,
        )
        # Risk should not exceed 2% of capital
        assert result["risk_amount"] <= 2000 + 1  # +1 for rounding

    def test_position_cap_constraint(self):
        """Position value should not exceed percentage cap."""
        result = calculate_position_size(
            capital=100000,
            entry_price=50,
            stop_loss=49,
            max_risk_pct=0.02,
            max_position_pct=0.20,
        )
        assert result["position_value"] <= 20000 + 50  # Allow for 1 share rounding

    def test_zero_risk_per_share(self):
        """Should handle entry == stop_loss gracefully."""
        result = calculate_position_size(
            capital=100000, entry_price=100, stop_loss=100
        )
        assert result["shares"] == 0

    def test_invalid_inputs(self):
        result = calculate_position_size(capital=0, entry_price=100, stop_loss=90)
        assert result["shares"] == 0

    def test_small_capital(self):
        result = calculate_position_size(
            capital=10000, entry_price=5000, stop_loss=4900
        )
        assert result["shares"] >= 0
        assert result["position_value"] <= 10000

    def test_kelly_negative_expectation(self):
        """Kelly fraction <= 0 should reject the trade (shares=0)."""
        result = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=95,
            win_probability=0.3,
            risk_reward=2.0
        )
        assert result["shares"] == 0
        assert result["position_value"] == 0.0
        assert result["risk_amount"] == 0.0
        assert result["risk_pct"] == 0.0
        assert result["capital_used_pct"] == 0.0
        assert "error" in result or "reason" in result

    def test_stop_loss_direction_validation_long(self):
        """If direction is 'long' and stop_loss >= entry_price, the trade should be rejected with zeroed values."""
        result = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=105,
            direction="long",
        )
        assert result["shares"] == 0
        assert result["entry_price"] == 100
        assert result["stop_loss"] == 105
        assert result["risk_per_share"] == 0.0
        assert result["position_value"] == 0.0
        assert result["risk_amount"] == 0.0
        assert result["risk_pct"] == 0.0
        assert result["capital_used_pct"] == 0.0
        assert result["error"] == "Stop loss must be below entry price for long trades"

        result_equal = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=100,
            direction="long",
        )
        assert result_equal["shares"] == 0
        assert result_equal["error"] == "Stop loss must be below entry price for long trades"

    def test_kelly_expectation_epsilon_check(self):
        """Kelly fraction of exactly 0 or 5.55e-17 due to precision should be rejected."""
        # e.g., p=0.4, q=0.6, b=1.5 -> p - q/b = 0.4 - 0.6/1.5 = 0
        result = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=95,
            win_probability=0.4,
            risk_reward=1.5
        )
        assert result["shares"] == 0
        assert "error" in result




class TestStopLossTarget:
    def test_long_stop_loss(self):
        sl = calculate_stop_loss(1000, atr=20, multiplier=1.5, direction="long")
        assert sl == 970.0

    def test_short_stop_loss(self):
        sl = calculate_stop_loss(1000, atr=20, multiplier=1.5, direction="short")
        assert sl == 1030.0

    def test_long_target(self):
        target = calculate_target(1000, atr=20, multiplier=3.0, direction="long")
        assert target == 1060.0

    def test_short_target(self):
        target = calculate_target(1000, atr=20, multiplier=3.0, direction="short")
        assert target == 940.0


class TestRiskReward:
    def test_basic_rr(self):
        rr = calculate_risk_reward(entry_price=100, stop_loss=95, target=115)
        assert rr == 3.0  # 15 reward / 5 risk

    def test_rr_two_to_one(self):
        rr = calculate_risk_reward(entry_price=100, stop_loss=90, target=120)
        assert rr == 2.0

    def test_rr_zero_risk(self):
        rr = calculate_risk_reward(entry_price=100, stop_loss=100, target=110)
        assert rr == 0
