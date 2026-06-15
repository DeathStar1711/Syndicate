"""
Position sizing module.
Implements strict 1-2% capital risk rule with configurable position caps.
"""
import math
from typing import Dict, Optional
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.strategy")


def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    max_risk_pct: float = 0.02,
    max_position_pct: float = 0.20,
    win_probability: Optional[float] = None,
    risk_reward: Optional[float] = None,
) -> Dict[str, float]:
    """
    Calculate position size based on risk management rules.
    
    Args:
        capital: Total available capital (INR)
        entry_price: Planned entry price
        stop_loss: Stop-loss price
        max_risk_pct: Maximum risk per trade as fraction of capital (default 2%)
        max_position_pct: Maximum position size as fraction of capital (default 20%)
    
    Returns:
        Dictionary with position sizing details
    """
    if entry_price <= 0 or stop_loss <= 0 or capital <= 0:
        logger.error("Invalid inputs for position sizing")
        return {"shares": 0, "risk_amount": 0, "position_value": 0, "error": "Invalid inputs"}

    # Risk per share
    risk_per_share = abs(entry_price - stop_loss)
    
    if risk_per_share <= 0:
        logger.error("Stop-loss equals entry price — cannot calculate position size")
        return {"shares": 0, "risk_amount": 0, "position_value": 0, "error": "Zero risk per share"}

    # Kelly Criterion adjustment
    if win_probability is not None and risk_reward is not None and risk_reward > 0:
        # Kelly fraction: f* = p - (1-p)/b
        p = win_probability
        q = 1.0 - p
        b = risk_reward
        kelly_fraction = p - (q / b)
        
        if kelly_fraction > 0:
            # Half-Kelly for safety
            half_kelly = kelly_fraction / 2.0
            # Cap Kelly fraction by the user's maximum risk to prevent overallocation
            dynamic_risk_pct = min(max_risk_pct, half_kelly)
            logger.debug(f"Kelly fraction: {kelly_fraction:.3f}, Using risk: {dynamic_risk_pct:.3f}")
            max_risk_pct = dynamic_risk_pct
        else:
            # Negative expectation according to Kelly, risk minimum
            max_risk_pct = 0.0025 # 0.25% minimum risk for extremely low probability trades

    # Maximum amount willing to lose on this trade
    max_risk_amount = capital * max_risk_pct
    
    # Maximum position value
    max_position_value = capital * max_position_pct
    
    # Calculate shares based on risk
    shares_by_risk = math.floor(max_risk_amount / risk_per_share)
    
    # Calculate shares based on position cap
    shares_by_position = math.floor(max_position_value / entry_price)
    
    # Take the smaller of the two
    shares = min(shares_by_risk, shares_by_position)
    shares = max(shares, 0)  # Never negative
    
    # Final calculations
    position_value = shares * entry_price
    actual_risk = shares * risk_per_share
    actual_risk_pct = (actual_risk / capital) * 100 if capital > 0 else 0
    
    result = {
        "shares": shares,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "risk_per_share": round(risk_per_share, 2),
        "position_value": round(position_value, 2),
        "risk_amount": round(actual_risk, 2),
        "risk_pct": round(actual_risk_pct, 2),
        "capital_used_pct": round((position_value / capital) * 100, 2) if capital > 0 else 0,
    }
    
    logger.info(
        f"Position size: {shares} shares @ ₹{entry_price:.2f}, "
        f"Risk: ₹{actual_risk:.2f} ({actual_risk_pct:.1f}%), "
        f"Position: ₹{position_value:.2f}"
    )
    
    return result


def calculate_stop_loss(entry_price: float, atr: float, multiplier: float = 1.5, direction: str = "long") -> float:
    """
    Calculate stop-loss price based on ATR.
    
    Args:
        entry_price: Entry price
        atr: Average True Range value
        multiplier: ATR multiplier for stop-loss distance
        direction: 'long' or 'short'
    
    Returns:
        Stop-loss price
    """
    sl_distance = atr * multiplier
    if direction == "long":
        return round(entry_price - sl_distance, 2)
    else:
        return round(entry_price + sl_distance, 2)


def calculate_target(entry_price: float, atr: float, multiplier: float = 3.0, direction: str = "long") -> float:
    """
    Calculate target price based on ATR.
    
    Args:
        entry_price: Entry price
        atr: Average True Range value
        multiplier: ATR multiplier for target distance
        direction: 'long' or 'short'
    
    Returns:
        Target price
    """
    target_distance = atr * multiplier
    if direction == "long":
        return round(entry_price + target_distance, 2)
    else:
        return round(entry_price - target_distance, 2)


def calculate_risk_reward(entry_price: float, stop_loss: float, target: float) -> float:
    """
    Calculate risk-reward ratio.
    
    Returns:
        Risk-reward ratio (e.g., 2.5 means 2.5:1 reward-to-risk)
    """
    risk = abs(entry_price - stop_loss)
    reward = abs(target - entry_price)
    
    if risk <= 0:
        return 0
    
    return round(reward / risk, 2)
