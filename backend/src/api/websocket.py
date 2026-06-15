"""
WebSocket endpoint for realtime dashboard updates.
Broadcasts: live prices (throttled 5s), signal updates, trade exits.
"""
import asyncio
import json
from typing import List, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.utils.logger import get_logger

logger = get_logger("stock_ai.api")
router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active: List[WebSocket] = []
        self.main_loop = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        if self.main_loop is None:
            self.main_loop = asyncio.get_running_loop()
        self.active.append(ws)
        logger.info(f"WebSocket connected ({len(self.active)} total)")

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info(f"WebSocket disconnected ({len(self.active)} total)")

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def broadcast_event(event_type: str, data: Any):
    """Broadcast an event to all connected clients."""
    await manager.broadcast({"type": event_type, "data": data})


async def broadcast_prices(prices: Dict[str, float]):
    """Broadcast live price updates."""
    await manager.broadcast({"type": "price_update", "data": prices})


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await ws.receive_text()
            msg = json.loads(data) if data else {}

            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
        manager.disconnect(ws)
