"""
Signals API routes.
GET /api/signals — today's signals
POST /api/signals/generate — force regenerate
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from src.utils.logger import get_logger
from src.utils.helpers import load_config, now_ist
from src.db.session import get_db, SessionLocal
from src.db.models import Signal

logger = get_logger("stock_ai.api")
router = APIRouter()

def _save_signals_to_db(signals_data: dict):
    """Save signals to database for persistence. Clears old signals first."""
    try:
        with SessionLocal() as db:
            # Clear all old signals — we only keep the latest batch
            db.query(Signal).delete()
            db.commit()

            timestamp = datetime.fromisoformat(signals_data["timestamp"])
            for sig in signals_data.get("data", []):
                new_signal = Signal(
                    ticker=sig.get("ticker"),
                    signal=sig.get("direction", "long"), # Or whatever key is used
                    confidence=sig.get("confidence", 0),
                    entry_price=sig.get("entry_price"),
                    stop_loss=sig.get("stop_loss"),
                    target=sig.get("target"),
                    reasoning=json.dumps(sig), # Store the full dict in reasoning for now to keep it flexible
                    date=timestamp,
                    executed=False
                )
                db.add(new_signal)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to save signals to db: {e}")

@router.get("")
async def get_signals(db = Depends(get_db)):
    """Get today's trade signals from the database."""
    # Find the most recent signal batch by date
    latest_signal = db.query(Signal).order_by(Signal.date.desc()).first()
    if not latest_signal:
        return {"timestamp": None, "data": [], "count": 0}
        
    # Get all signals from the same batch (same date/hour approximately, or same day)
    # We use date component since signals are generated daily
    target_date = latest_signal.date.date()
    
    signals = db.query(Signal).filter(
        Signal.date >= datetime.combine(target_date, datetime.min.time()),
        Signal.date <= datetime.combine(target_date, datetime.max.time())
    ).all()
    
    data = []
    for sig in signals:
        try:
            # We stored the raw dict in reasoning to ensure frontend compat
            raw_dict = json.loads(sig.reasoning)
            data.append(raw_dict)
        except:
            data.append({
                "ticker": sig.ticker,
                "direction": sig.signal,
                "confidence": sig.confidence,
                "entry_price": sig.entry_price,
                "stop_loss": sig.stop_loss,
                "target": sig.target,
            })
            
    return {
        "timestamp": latest_signal.date.isoformat(),
        "data": data,
        "count": len(data)
    }

@router.post("/generate")
async def generate_signals_now(background_tasks: BackgroundTasks):
    """Force regenerate signals now (runs in background)."""
    background_tasks.add_task(_run_signal_generation)
    return {"status": "generating", "message": "Signal generation started in background"}


def _broadcast_step(step: str, status: str, content: str = ""):
    """Broadcast a pipeline step event via WebSocket (fire-and-forget)."""
    try:
        from src.api.websocket import manager
        import asyncio

        event = {
            "type": "pipeline_step",
            "data": {
                "step": step,
                "ticker": "",
                "status": status,
                "content": content if content else "",
            }
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast(event))
        except RuntimeError:
            if hasattr(manager, "main_loop") and manager.main_loop:
                asyncio.run_coroutine_threadsafe(manager.broadcast(event), manager.main_loop)
    except Exception:
        pass


def _run_signal_generation():
    """Execute the full signal generation pipeline."""
    try:
        config = load_config()
        from src.strategy.signals import generate_signals
        from src.llm.signal_validator import batch_validate_signals
        from src.llm.market_briefing import get_cached_briefing

        # Step 1: Generate base signals from strategy engine
        _broadcast_step("Scanning Watchlist", "start", "Fetching data & computing indicators for all tickers...")
        signals = generate_signals(config=config)
        _broadcast_step("Scanning Watchlist", "done", f"Found {len(signals)} candidate signals")

        if signals:
            # Step 2: Get market context
            _broadcast_step("Market Context", "start", "Fetching market briefing & news...")
            briefing = get_cached_briefing()
            market_ctx = ""
            if briefing:
                market_ctx = (
                    f"Market Mood: {briefing.get('market_mood', 'N/A')}\n"
                    f"Summary: {briefing.get('summary', 'N/A')}\n"
                    f"Risk Factors: {', '.join(briefing.get('risk_factors', []))}"
                )

            _broadcast_step("Market Context", "done", f"Briefing: {briefing.get('market_mood', 'N/A') if briefing else 'N/A'}")

            # Step 3: LLM validation (graceful — skips if Ollama is down)
            _broadcast_step("LLM Validation", "start", f"Running AI debate for {len(signals)} signals...")
            signals = batch_validate_signals(
                signals,
                market_context=market_ctx,
            )
            _broadcast_step("LLM Validation", "done", f"Validated {len(signals)} signals")
        else:
            _broadcast_step("Scanning Watchlist", "done", "No trade setups found today")

        result = {
            "timestamp": now_ist().isoformat(),
            "data": signals,
            "count": len(signals),
        }

        _save_signals_to_db(result)

        # Broadcast final result to WebSocket clients
        try:
            from src.api.websocket import broadcast_event, manager
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(broadcast_event("signals_updated", result))
            except RuntimeError:
                if hasattr(manager, "main_loop") and manager.main_loop:
                    asyncio.run_coroutine_threadsafe(broadcast_event("signals_updated", result), manager.main_loop)
        except Exception:
            pass

        _broadcast_step("Pipeline Complete", "done", f"✅ {len(signals)} signals ready")
        logger.info(f"✅ Signals generated: {len(signals)} picks")

    except Exception as e:
        logger.error(f"Signal generation failed: {e}")
        _broadcast_step("Pipeline Error", "error", str(e)[:200])

@router.get("/{ticker}")
async def get_signal_detail(ticker: str, db = Depends(get_db)):
    """Get detailed signal for a specific ticker."""
    latest_signal = db.query(Signal).filter(Signal.ticker == ticker).order_by(Signal.date.desc()).first()
    if not latest_signal:
        return {"error": f"No signal found for {ticker}"}
        
    try:
        return json.loads(latest_signal.reasoning)
    except:
        return {
            "ticker": latest_signal.ticker,
            "direction": latest_signal.signal,
            "confidence": latest_signal.confidence,
            "entry_price": latest_signal.entry_price,
            "stop_loss": latest_signal.stop_loss,
            "target": latest_signal.target,
        }
