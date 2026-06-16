"""
Portfolio API routes.
Manages the user's active paper trading portfolio.
Trades are added at current market price (user's choice).
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.trading.paper_trader import PaperTrader
from src.data.fetcher import get_current_price
from src.utils.logger import get_logger
from src.utils.helpers import load_config, now_ist

logger = get_logger("stock_ai.api")
router = APIRouter()

# Singleton paper trader
_trader: Optional[PaperTrader] = None


def _get_trader() -> PaperTrader:
    global _trader
    if _trader is None:
        _trader = PaperTrader()
        config = load_config()
        capital = config.get("capital", {}).get("starting_amount", 100000)
        # Only set if it's a fresh DB
        try:
            current = _trader.get_capital()
            if current == 100000.0:
                _trader.set_capital(capital)
        except Exception:
            _trader.set_capital(capital)
    return _trader


class AddTradeRequest(BaseModel):
    """Request body for adding a signal to portfolio at current market price."""
    ticker: str
    direction: str = "long"
    stop_loss: float
    target: float
    confidence: int = 50
    risk_reward: float = 2.0
    reasons: list = []
    cons: list = []
    llm_verdict: Optional[str] = None
    llm_reasoning: Optional[str] = None
    shares: Optional[int] = None  # If provided, overrides calculated position size


class CloseTradeRequest(BaseModel):
    """Request body for closing a trade."""
    exit_reason: str = "manual"


@router.get("")
async def get_portfolio():
    """Get full portfolio: summary + open positions with live P&L."""
    import math

    def _valid_price(p):
        """Check if a price value is usable (not None, NaN, or Inf)."""
        if p is None:
            return False
        try:
            return not (math.isnan(p) or math.isinf(p))
        except TypeError:
            return False

    trader = _get_trader()
    summary = trader.get_portfolio_summary()
    open_positions = trader.get_open_positions()

    # Enrich with live prices
    if open_positions:
        tickers = list(set(p["ticker"] for p in open_positions))
        from src.data.fetcher import get_current_prices
        live_prices = get_current_prices(tickers, use_live_api=True)

        for pos in open_positions:
            ticker = pos["ticker"]
            current_price = live_prices.get(ticker)

            if _valid_price(current_price):
                entry = pos["entry_price"] or 0
                shares = pos["shares"] or 0
                direction = pos.get("direction", "long")

                if direction == "long":
                    unrealized_pnl = (current_price - entry) * shares
                else:
                    unrealized_pnl = (entry - current_price) * shares

                pos["current_price"] = round(current_price, 2)
                pos["unrealized_pnl"] = round(unrealized_pnl, 2)
                denom = entry * shares
                pos["unrealized_pnl_pct"] = round((unrealized_pnl / denom) * 100, 2) if denom > 0 else 0.0

                # Progress toward target vs stop loss
                sl = pos.get("stop_loss") or 0
                tgt = pos.get("target") or 0
                total_range = tgt - sl
                if total_range > 0:
                    pos["progress_pct"] = round(((current_price - sl) / total_range) * 100, 1)
                else:
                    pos["progress_pct"] = 50.0
            else:
                pos["current_price"] = None
                pos["unrealized_pnl"] = None
                pos["unrealized_pnl_pct"] = None
                pos["progress_pct"] = None

    return {
        "summary": summary,
        "open_positions": open_positions,
    }


@router.get("/history")
async def get_trade_history(limit: int = 50):
    """Get closed trade history."""
    trader = _get_trader()
    trades = trader.get_closed_trades(limit=limit)
    return {"trades": trades, "count": len(trades)}


@router.post("/add")
async def add_trade_to_portfolio(req: AddTradeRequest):
    """
    Add a signal to the portfolio at CURRENT MARKET PRICE.
    The user clicks 'Add to Portfolio' on the dashboard,
    and the trade opens at whatever the market price is NOW.
    """
    trader = _get_trader()
    config = load_config()
    capital_config = config.get("capital", {})

    # Get current market price
    current_price = get_current_price(req.ticker, use_live_api=True)
    if current_price is None:
        raise HTTPException(status_code=400, detail=f"Cannot fetch live price for {req.ticker}")

    # Recalculate position sizing at current price
    from src.strategy.position_sizing import calculate_position_size
    capital = trader.get_capital()
    position = calculate_position_size(
        capital=capital,
        entry_price=current_price,
        stop_loss=req.stop_loss,
        max_risk_pct=capital_config.get("max_risk_per_trade_pct", 0.02),
        max_position_pct=capital_config.get("max_position_pct", 0.20),
    )

    # Override with user-specified shares if provided
    if req.shares is not None and req.shares > 0:
        position["shares"] = req.shares
        position["position_value"] = round(current_price * req.shares, 2)
        position["risk_amount"] = round(abs(current_price - req.stop_loss) * req.shares, 2)

    if position["shares"] <= 0:
        raise HTTPException(
            status_code=400,
            detail="Position size is 0 — insufficient capital or risk too high"
        )

    # Build signal dict for paper_trader.open_trade()
    signal = {
        "ticker": req.ticker,
        "direction": req.direction,
        "entry_price": current_price,
        "stop_loss": req.stop_loss,
        "target": req.target,
        "risk_reward": req.risk_reward,
        "confidence": req.confidence,
        "reasons": req.reasons,
        "position": position,
        "trade_type": "dashboard_manual",
        "atr": abs(current_price - req.stop_loss) / 1.5,  # Approximate ATR
        "trend": "unknown",
        "volatility_regime": "normal",
    }

    trade_id = trader.open_trade(signal)
    if trade_id <= 0:
        raise HTTPException(status_code=500, detail="Failed to open trade")

    logger.info(
        f"📊 Dashboard trade opened: #{trade_id} {req.ticker} "
        f"@ ₹{current_price:.2f} ({position['shares']} shares)"
    )

    return {
        "trade_id": trade_id,
        "ticker": req.ticker,
        "entry_price": current_price,
        "shares": position["shares"],
        "position_value": position["position_value"],
        "risk_amount": position["risk_amount"],
        "message": f"Trade opened at ₹{current_price:.2f}",
    }


@router.post("/close/{trade_id}")
async def close_trade(trade_id: int, req: CloseTradeRequest):
    """Close a trade at current market price."""
    import math
    trader = _get_trader()

    # Find the trade
    open_positions = trader.get_open_positions()
    trade = next((t for t in open_positions if t["id"] == trade_id), None)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade #{trade_id} not found or already closed")

    # Get current price — guard against NaN (market closed)
    current_price = get_current_price(trade["ticker"], use_live_api=True)
    
    if current_price is not None:
        try:
            current_price = float(current_price)
            if math.isnan(current_price) or math.isinf(current_price):
                current_price = None
        except (ValueError, TypeError):
            current_price = None

    if current_price is None:
        raise HTTPException(
            status_code=400,
            detail=f"Market is closed or price unavailable for {trade['ticker'].replace('.NS', '')}. Try again during market hours."
        )

    result = trader.close_trade(trade_id, current_price, req.exit_reason)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result

