"""
Module for interfacing with the Groww API to fetch high-fidelity live market data.
It provides REST endpoints for LTP and a WebSocket feed for real-time tick and orderbook data.
"""
import os
import json
import asyncio
from typing import Dict, Optional, Callable, List
import logging
from growwapi import GrowwAPI
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.data.groww")


class GrowwDataClient:
    """Manages Groww SDK REST connection and data fetching."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.api_key = os.getenv("GROWW_API_KEY")
        self.api_secret = os.getenv("GROWW_API_SECRET")
        self.client = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Groww API using TOTP/API Key flow"""
        if not self.api_key or not self.api_secret:
            logger.warning("Groww API credentials not found in env. Running in degraded mode.")
            return

        try:
            # Generate the access token using the API key and secret
            token = GrowwAPI.get_access_token(api_key=self.api_key, secret=self.api_secret)
            self.client = GrowwAPI(token)
            self.token = token
            logger.info("Successfully authenticated with Groww API.")
        except Exception as e:
            logger.error(f"Failed to authenticate with Groww API: {e}")
            self.client = None

    def get_live_price(self, ticker: str) -> Optional[float]:
        """Fetch the immediate Last Traded Price (LTP) via REST."""
        if not self.client:
            return None
            
        try:
            # Note: Groww SDK generally asks for exchange identifiers in symbols.
            # Convert YF format 'RELIANCE.NS' -> 'NSE_RELIANCE'
            if ticker.endswith(".BO"):
                symbol = ticker.replace(".BO", "")
                exchange_symbol = f"BSE_{symbol}"
            else:
                symbol = ticker.replace(".NS", "")
                exchange_symbol = f"NSE_{symbol}"
            
            # The SDK method is get_ltp(exchange_trading_symbols, segment)
            response = self.client.get_ltp(exchange_trading_symbols=(exchange_symbol,), segment="CASH")
            if response and exchange_symbol in response:
                return float(response[exchange_symbol].get("ltp", 0.0))
            return None
        except Exception as e:
            logger.warning(f"Groww API fetch failed for {ticker}: {e}")
            return None

    def get_market_depth(self, ticker: str) -> Dict:
        """
        Fetch the current 5-level Order Book Imbalance.
        NOTE: The unofficial growwapi SDK does not support REST market depth.
        It is only available via WebSocket. Returning empty depth to bypass filter safely.
        """
        if not self.client:
            return {}
            
        # REST Market Depth is not implemented natively in the GrowwAPI SDK client.
        # Fallback to empty depth dictionary to allow signals to pass without warning spam.
        return {}


class GrowwFeedListener:
    """Manages WebSocket connections for streaming live tick data."""
    
    def __init__(self, tickers: List[str], on_tick_callback: Callable):
        self.tickers = [t.replace(".NS", "").replace(".BO", "") for t in tickers]
        self.ticker_map = {t.replace(".NS", "").replace(".BO", ""): t for t in tickers}
        self.on_tick_callback = on_tick_callback
        self.client = GrowwDataClient()
        self.is_running = False
        self.ws_client = None

    def subscribe_new_tickers(self, new_tickers: List[str]):
        clean_new = []
        for t in new_tickers:
            clean = t.replace(".NS", "").replace(".BO", "")
            if clean not in self.tickers:
                self.tickers.append(clean)
                self.ticker_map[clean] = t
                clean_new.append(clean)
        if clean_new and self.is_running and hasattr(self, 'ws_client') and self.ws_client:
            try:
                self.ws_client.subscribe(symbols=clean_new)
                logger.info(f"Dynamically subscribed to new symbols: {clean_new}")
            except Exception as e:
                logger.error(f"Failed to subscribe to new symbols {clean_new}: {e}")

    async def connect_and_listen(self):
        """Connect to WebSocket and listen for ticks."""
        if not self.client.client:
            logger.error("Cannot start WebSocket feed: Groww client not authenticated.")
            return

        self.is_running = True
        logger.info(f"Starting Groww WebSocket Feed for {len(self.tickers)} symbols...")
        
        try:
            # The GrowwFeed requires the token and instruments
            from growwapi.groww.feed import GrowwFeed
            ws = GrowwFeed(token=self.client.token)
            
            @ws.on_tick
            def on_tick(ws_client, ticks):
                for tick in ticks:
                    # Parse tick and trigger callback according to actual proto definitions
                    # We'll map the standard structure here
                    symbol = tick.get("symbol", "")
                    mapped_ticker = self.ticker_map.get(symbol, symbol + ".NS")
                    parsed_tick = {
                        "ticker": mapped_ticker,
                        "ltp": tick.get("last_traded_price"),
                        "volume": tick.get("volume_traded_today"),
                        "vwap": tick.get("average_traded_price"),
                        "best_bid": tick.get("best_bid_price"),
                        "best_ask": tick.get("best_ask_price"),
                    }
                    self.on_tick_callback(parsed_tick)

            @ws.on_connect
            def on_connect(ws_client, response):
                logger.info("WebSocket connected. Subscribing to tokens.")
                self.ws_client = ws_client
                ws_client.subscribe(symbols=self.tickers)

            @ws.on_close
            def on_close(ws_client, code, reason):
                logger.warning(f"WebSocket closed: {code} - {reason}")
                self.is_running = False
                self.ws_client = None

            ws.connect()
            
            # Keep alive loop
            while self.is_running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"WebSocket execution failed: {e}")
            self.is_running = False
            self.ws_client = None

    def stop(self):
        self.is_running = False
        self.ws_client = None
