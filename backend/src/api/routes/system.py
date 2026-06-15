"""
System API routes — health, config, manual task triggers.
"""
from fastapi import APIRouter, BackgroundTasks
from src.utils.logger import get_logger
from src.utils.helpers import load_config, now_ist, is_market_hours

logger = get_logger("stock_ai.api")
router = APIRouter()


@router.get("/health")
async def health_check():
    from src.llm.client import get_llm_client
    client = get_llm_client()
    return {
        "status": "ok",
        "timestamp": now_ist().isoformat(),
        "market_open": is_market_hours(),
        "llm": client.get_status(),
    }


@router.get("/config")
async def get_config():
    config = load_config()
    return {
        "capital": config.get("capital", {}),
        "strategy": config.get("strategy", {}),
        "trading": config.get("trading", {}),
        "llm": {"enabled": config.get("llm", {}).get("enabled", True), "model": config.get("llm", {}).get("model", "gemma4:e4b")},
    }


@router.get("/ml-status")
async def get_ml_status():
    import os
    import joblib
    from src.utils.helpers import get_data_dir

    model_dir = os.path.join(get_data_dir(), "models")
    meta_path = os.path.join(model_dir, "model_metadata.pkl")
    model_path = os.path.join(model_dir, "model_latest.pkl")

    model_exists = os.path.exists(model_path)
    metadata = {}

    def _sanitize(v):
        if isinstance(v, dict):
            return {k: _sanitize(val) for k, val in v.items()}
        elif isinstance(v, list):
            return [_sanitize(x) for x in v]
        elif hasattr(v, "item"):
            return v.item()
        return v

    if model_exists and os.path.exists(meta_path):
        try:
            metadata = _sanitize(joblib.load(meta_path))
        except Exception as e:
            logger.error(f"Failed to load ML metadata: {e}")

    return {
        "model_exists": model_exists,
        "metadata": metadata,
    }


@router.post("/run/{task}")
async def run_task(task: str, background_tasks: BackgroundTasks):
    valid = {"generate_signals", "market_briefing", "retrain", "check_exits"}
    if task not in valid:
        return {"error": f"Unknown task. Valid: {list(valid)}"}

    if task == "generate_signals":
        from src.api.routes.signals import _run_signal_generation
        background_tasks.add_task(_run_signal_generation)
    elif task == "market_briefing":
        from src.llm.market_briefing import clear_briefing_cache
        clear_briefing_cache()
    elif task == "retrain":
        def _retrain():
            from src.ml.retrain import retrain_model
            retrain_model()
        background_tasks.add_task(_retrain)
    elif task == "check_exits":
        def _check():
            from src.trading.intraday_monitor import IntradayMonitor
            IntradayMonitor().check_exits(force=True)
        background_tasks.add_task(_check)

    return {"status": "started", "task": task}
