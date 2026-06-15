"""
FastAPI application server for Stock-AI V2.
Serves REST API + WebSocket for the dashboard frontend.
Starts APScheduler on lifespan.
"""
import os
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.api")

# Load environment variables
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("🚀 Stock-AI V2 API starting...")

    # Start scheduler
    from src.scheduler.jobs import start_scheduler
    scheduler = start_scheduler()
    app.state.scheduler = scheduler

    # Check Ollama health
    from src.llm.client import get_llm_client
    client = get_llm_client()
    if client.is_healthy():
        logger.info("✅ Ollama connection OK — Gemma 4 E4B available")
    else:
        logger.warning("⚠️ Ollama unavailable — LLM features will be disabled")

    logger.info("✅ Stock-AI V2 API ready")
    yield

    # Shutdown
    logger.info("Shutting down scheduler...")
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown(wait=False)
    logger.info("Stock-AI V2 API stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = load_config()

    app = FastAPI(
        title="Stock-AI V2",
        description="LLM-augmented intraday trading system for Indian markets",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS — allow frontend dev server and ngrok
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            frontend_url,
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"https://.*\.ngrok-free\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
    from src.api.routes.signals import router as signals_router
    from src.api.routes.portfolio import router as portfolio_router
    from src.api.routes.market import router as market_router
    from src.api.routes.trades import router as trades_router
    from src.api.routes.system import router as system_router
    from src.api.websocket import router as ws_router

    app.include_router(signals_router, prefix="/api/signals", tags=["Signals"])
    app.include_router(portfolio_router, prefix="/api/portfolio", tags=["Portfolio"])
    app.include_router(market_router, prefix="/api/market", tags=["Market"])
    app.include_router(trades_router, prefix="/api/trades", tags=["Trades"])
    app.include_router(system_router, prefix="/api/system", tags=["System"])
    app.include_router(ws_router, tags=["WebSocket"])

    @app.get("/")
    async def root():
        return {"name": "Stock-AI V2", "version": "2.0.0", "status": "running"}

    return app
