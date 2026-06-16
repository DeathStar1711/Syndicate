"""
Paper trading portfolio tracker using SQLite.
Manages open/closed trades and portfolio state without real money.
"""
import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import func
from src.utils.logger import get_logger
from src.utils.helpers import get_data_dir, now_ist
from src.db.session import SessionLocal, init_db
from src.db.models import PortfolioState, DailySnapshot, Trade

logger = get_logger("stock_ai.trading")

class PaperTrader:
    """SQLAlchemy-backed paper trading portfolio manager."""

    def __init__(self, db_path: Optional[str] = None):
        # The database initialization is handled by src.db.session now
        init_db()
        self._init_portfolio_state()

    def _init_portfolio_state(self):
        """Ensure starting capital exists."""
        with SessionLocal() as db:
            starting = db.query(PortfolioState).filter(PortfolioState.key == "starting_capital").first()
            if not starting:
                db.add(PortfolioState(key="starting_capital", value="100000"))
                db.add(PortfolioState(key="current_capital", value="100000"))
                db.commit()

    def set_capital(self, amount: float):
        """Set the starting and current capital."""
        with SessionLocal() as db:
            starting = db.query(PortfolioState).filter(PortfolioState.key == "starting_capital").first()
            if starting:
                starting.value = str(amount)
            else:
                db.add(PortfolioState(key="starting_capital", value=str(amount)))
                
            current = db.query(PortfolioState).filter(PortfolioState.key == "current_capital").first()
            if current:
                current.value = str(amount)
            else:
                db.add(PortfolioState(key="current_capital", value=str(amount)))
            db.commit()

    def get_capital(self) -> float:
        """Get current available capital."""
        with SessionLocal() as db:
            current = db.query(PortfolioState).filter(PortfolioState.key == "current_capital").first()
            return float(current.value) if current else 100000.0

    def open_trade(self, signal: Dict) -> int:
        """Open a new paper trade from a signal."""
        position = signal.get("position", {})
        shares = position.get("shares", 0)
        position_value = position.get("position_value", 0)

        if shares <= 0:
            logger.warning(f"Cannot open trade for {signal['ticker']} — 0 shares")
            return -1

        metadata_dict = {
            "atr": signal.get("atr"),
            "rsi": signal.get("rsi"),
            "trend": signal.get("trend"),
            "volatility_regime": signal.get("volatility_regime"),
            "trade_type": signal.get("trade_type", "daily"),
        }

        trade = Trade(
            ticker=signal["ticker"],
            direction=signal.get("direction", "long"),
            entry_price=signal["entry_price"],
            stop_loss=signal["stop_loss"],
            target=signal["target"],
            shares=shares,
            position_value=position_value,
            risk_amount=position.get("risk_amount", 0),
            risk_reward=signal.get("risk_reward", 0),
            confidence=signal.get("confidence", 0),
            reasons=json.dumps(signal.get("reasons", [])),
            entry_date=now_ist().isoformat(),
            status="open",
            metadata_json=json.dumps(metadata_dict)
        )

        with SessionLocal() as db:
            db.add(trade)
            db.commit()
            db.refresh(trade)
            trade_id = trade.id

            current_capital = self.get_capital()
            new_capital = current_capital - position_value
            
            cap_state = db.query(PortfolioState).filter(PortfolioState.key == "current_capital").first()
            if cap_state:
                cap_state.value = str(new_capital)
            db.commit()

        logger.info(
            f"TRADE OPENED: #{trade_id} {signal['ticker']} | "
            f"{shares} shares @ ₹{signal['entry_price']:.2f} | "
            f"Value: ₹{position_value:,.2f}"
        )

        return trade_id

    def close_trade(self, trade_id: int, exit_price: float, exit_reason: str = "manual") -> Dict:
        """Close an open trade."""
        with SessionLocal() as db:
            trade = db.query(Trade).filter(Trade.id == trade_id, Trade.status == "open").first()
            if not trade:
                return {"error": f"Trade #{trade_id} not found or already closed"}

            shares = trade.shares
            entry_price = trade.entry_price
            direction = trade.direction

            if direction == "long":
                gross_pnl = (exit_price - entry_price) * shares
            else:
                gross_pnl = (entry_price - exit_price) * shares

            turnover = (entry_price + exit_price) * shares
            brokerage = turnover * 0.001
            pnl = gross_pnl - brokerage
            pnl_pct = (pnl / (entry_price * shares)) * 100

            trade.exit_price = exit_price
            trade.exit_date = now_ist().isoformat()
            trade.exit_reason = exit_reason
            trade.pnl = round(pnl, 2)
            trade.pnl_pct = round(pnl_pct, 2)
            trade.status = "closed"
            
            position_value = trade.position_value
            
            # Atomic update of capital
            from sqlalchemy import text
            delta = position_value + pnl
            db.execute(
                text("UPDATE portfolio_state SET value = CAST(CAST(value AS REAL) + :delta AS TEXT) WHERE key = 'current_capital'"),
                {"delta": delta}
            )
            
            db.commit()
            db.refresh(trade)
            
            # Need dictionary copy for the mistake journal
            trade_dict = {
                "id": trade.id,
                "ticker": trade.ticker,
                "entry_price": trade.entry_price,
                "stop_loss": trade.stop_loss,
                "entry_date": trade.entry_date,
                "metadata": trade.metadata_json
            }

        result = {
            "trade_id": trade_id,
            "ticker": trade_dict["ticker"],
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "shares": shares,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "exit_reason": exit_reason,
            "is_winner": pnl > 0,
            "exit_date": trade.exit_date
        }

        emoji = "✅" if pnl > 0 else "❌"
        logger.info(
            f"{emoji} TRADE CLOSED: #{trade_id} {trade_dict['ticker']} | "
            f"P&L: ₹{pnl:,.2f} ({pnl_pct:+.1f}%) | Reason: {exit_reason}"
        )

        if exit_reason == "stop_loss":
            self._record_mistake(trade_dict, result)

        return result

    def _record_mistake(self, trade: Dict, result: Dict):
        """Record a stop-loss exit in the MistakeJournal."""
        try:
            from src.ml.mistake_journal import MistakeJournal
            from src.data.news import fetch_news_for_event

            ticker = trade["ticker"]
            exit_date = result.get("exit_date") or now_ist().isoformat()

            technical_data = {}
            if trade.get("metadata"):
                try:
                    technical_data = json.loads(trade["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass

            try:
                news_headlines = fetch_news_for_event(ticker, exit_date, window_days=2)
            except Exception:
                news_headlines = []

            trade_context = {
                "trade_id": trade["id"],
                "ticker": ticker,
                "entry_date": trade["entry_date"],
                "exit_date": exit_date,
                "entry_price": trade["entry_price"],
                "exit_price": result.get("exit_price"),
                "stop_loss": trade["stop_loss"],
                "pnl": result.get("pnl", 0),
                "pnl_pct": result.get("pnl_pct", 0),
                "exit_reason": "stop_loss",
            }

            journal = MistakeJournal()
            journal.record_mistake(trade_context, technical_data, news_headlines)

        except Exception as e:
            logger.debug(f"Mistake recording failed (non-critical): {e}")

    @staticmethod
    def _trade_to_dict(t: Trade) -> Dict:
        """Convert a Trade ORM object to a plain dict, avoiding the SQLAlchemy
        Base.metadata attribute collision. Also sanitizes NaN/Inf floats."""
        import math

        def _safe(v):
            """Replace NaN / Inf with None so JSON serialization doesn't explode."""
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            return v

        return {
            "id": t.id,
            "ticker": t.ticker,
            "direction": t.direction,
            "entry_price": _safe(t.entry_price),
            "stop_loss": _safe(t.stop_loss),
            "target": _safe(t.target),
            "shares": t.shares,
            "position_value": _safe(t.position_value),
            "risk_amount": _safe(t.risk_amount),
            "risk_reward": _safe(t.risk_reward),
            "confidence": t.confidence,
            "reasons": t.reasons,
            "entry_date": t.entry_date,
            "exit_price": _safe(t.exit_price),
            "exit_date": t.exit_date,
            "exit_reason": t.exit_reason,
            "pnl": _safe(t.pnl),
            "pnl_pct": _safe(t.pnl_pct),
            "status": t.status,
            "metadata_json": t.metadata_json,
        }

    def get_open_positions(self) -> List[Dict]:
        """Get all open trades."""
        with SessionLocal() as db:
            trades = db.query(Trade).filter(Trade.status == "open").order_by(Trade.entry_date.desc()).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_closed_trades(self, limit: int = 100) -> List[Dict]:
        """Get recent closed trades."""
        with SessionLocal() as db:
            trades = db.query(Trade).filter(Trade.status == "closed").order_by(Trade.exit_date.desc()).limit(limit).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_portfolio_summary(self) -> Dict:
        """Get current portfolio summary."""
        import math

        def _sr(v, digits=2):
            """Safe round: handles NaN, None, and non-float gracefully."""
            if v is None:
                return 0.0
            try:
                f = float(v)
                return 0.0 if math.isnan(f) or math.isinf(f) else round(f, digits)
            except (TypeError, ValueError):
                return 0.0

        with SessionLocal() as db:
            starting_state = db.query(PortfolioState).filter(PortfolioState.key == "starting_capital").first()
            starting_capital = float(starting_state.value) if starting_state else 100000.0
            
            current_capital = self.get_capital()

            open_count = db.query(func.count(Trade.id)).filter(Trade.status == "open").scalar() or 0
            open_value = db.query(func.sum(Trade.position_value)).filter(Trade.status == "open").scalar() or 0.0

            total_trades = db.query(func.count(Trade.id)).filter(Trade.status == "closed").scalar() or 0
            wins = db.query(func.count(Trade.id)).filter(Trade.status == "closed", Trade.pnl > 0).scalar() or 0
            losses = db.query(func.count(Trade.id)).filter(Trade.status == "closed", Trade.pnl <= 0).scalar() or 0
            
            total_pnl = db.query(func.sum(Trade.pnl)).filter(Trade.status == "closed").scalar() or 0.0
            total_profit_amount = db.query(func.sum(Trade.pnl)).filter(Trade.status == "closed", Trade.pnl > 0).scalar() or 0.0
            total_loss_amount = db.query(func.sum(Trade.pnl)).filter(Trade.status == "closed", Trade.pnl <= 0).scalar() or 0.0
            
            avg_pnl = db.query(func.avg(Trade.pnl)).filter(Trade.status == "closed").scalar() or 0.0
            best_trade = db.query(func.max(Trade.pnl)).filter(Trade.status == "closed").scalar() or 0.0
            worst_trade = db.query(func.min(Trade.pnl)).filter(Trade.status == "closed").scalar() or 0.0

            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            pl_ratio = abs(total_profit_amount / total_loss_amount) if total_loss_amount != 0 else (total_profit_amount if total_profit_amount > 0 else 0)

            return {
                "starting_capital": _sr(starting_capital),
                "current_capital": _sr(current_capital),
                "invested_capital": _sr(open_value),
                "available_capital": _sr(current_capital),
                "total_capital": _sr(current_capital + open_value),
                "open_positions": open_count,
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": _sr(win_rate, 1),
                "total_pnl": _sr(total_pnl),
                "total_profit_amount": _sr(total_profit_amount),
                "total_loss_amount": _sr(total_loss_amount),
                "pl_ratio": _sr(pl_ratio),
                "avg_pnl": _sr(avg_pnl),
                "best_trade": _sr(best_trade),
                "worst_trade": _sr(worst_trade),
                "return_pct": _sr(((current_capital + open_value - starting_capital) / starting_capital) * 100) if starting_capital else 0,
            }

    def save_daily_snapshot(self):
        """Save a daily portfolio snapshot."""
        summary = self.get_portfolio_summary()
        today = now_ist().strftime("%Y-%m-%d")

        with SessionLocal() as db:
            snapshot = db.query(DailySnapshot).filter(DailySnapshot.date == today).first()
            if not snapshot:
                snapshot = DailySnapshot(date=today)
                db.add(snapshot)
            
            snapshot.total_capital = summary["total_capital"]
            snapshot.invested_capital = summary["invested_capital"]
            snapshot.available_capital = summary["available_capital"]
            snapshot.open_positions = summary["open_positions"]
            snapshot.daily_pnl = 0  # To be updated if needed
            snapshot.cumulative_pnl = summary["total_pnl"]
            snapshot.win_count = summary["wins"]
            snapshot.loss_count = summary["losses"]
            snapshot.total_trades = summary["total_trades"]
            
            db.commit()
            logger.info(f"Daily snapshot saved for {today}")
