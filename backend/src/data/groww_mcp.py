import asyncio
import json
import threading
import time
from typing import List, Dict, Optional, Any
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from contextlib import AsyncExitStack
from src.utils.logger import get_logger

logger = get_logger("stock_ai.groww_mcp")

# ── Configuration ────────────────────────────────────────────────────────────
MCP_REMOTE_VERSION = "0.1.38"
MCP_SERVER_URL = "https://mcp.groww.in/mcp"
MCP_CALLBACK_PORT = "52155"
MAX_CONNECT_ATTEMPTS = 3          # Try a few times
CONNECT_RETRY_COOLDOWN = 10       # 10 seconds cooldown instead of 5 minutes


class GrowwMCPClient:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self._stack: Optional[AsyncExitStack] = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._start_background_loop, daemon=True)
        self._thread.start()
        self._connecting = False
        self._connected_event = threading.Event()
        self._connect_attempts = 0
        self._last_failure_time: float = 0
        
        # Start connection in background — non-blocking
        self._connect_background()

    def _start_background_loop(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.run_until_complete(self._cleanup_async())

    def _connect_background(self):
        """Start MCP connection in background without blocking startup."""
        if self._connecting:
            return
        
        # Circuit breaker — don't retry too soon after failure
        if self._connect_attempts >= MAX_CONNECT_ATTEMPTS:
            elapsed = time.time() - self._last_failure_time
            if elapsed < CONNECT_RETRY_COOLDOWN:
                logger.warning(
                    f"Groww MCP: skipping reconnect (cooldown {int(CONNECT_RETRY_COOLDOWN - elapsed)}s remaining). "
                    f"Authorize manually then restart, or wait for cooldown."
                )
                return

            # Cooldown expired — allow one more attempt
            self._connect_attempts = 0

        self._connecting = True
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self._loop)
        
        def _on_done(fut):
            self._connecting = False
            self._connect_attempts += 1
            try:
                fut.result()
                self._connected_event.set()
                self._connect_attempts = 0  # Reset on success
            except Exception as e:
                self._last_failure_time = time.time()
                logger.warning(
                    f"Groww MCP connection failed (attempt {self._connect_attempts}/{MAX_CONNECT_ATTEMPTS}): {e}"
                )
                if self._connect_attempts >= MAX_CONNECT_ATTEMPTS:
                    logger.warning(
                        f"⚠️  Groww MCP: max attempts reached. Price data will be unavailable. "
                        f"To fix: authorize at the Groww URL that was printed above, then restart the app."
                    )
        
        future.add_done_callback(_on_done)

    @classmethod
    def get_instance(cls) -> "GrowwMCPClient":
        with cls._lock:
            if cls._instance is None:
                cls._instance = GrowwMCPClient()
            return cls._instance

    def is_ready(self) -> bool:
        """Check if the MCP session is connected and ready."""
        return self.session is not None

    def wait_until_ready(self, timeout: float = 30) -> bool:
        """Wait until connected, with a timeout. Returns True if ready."""
        if self.is_ready():
            return True
        return self._connected_event.wait(timeout=timeout)

    async def _connect_async(self):
        logger.info("Initializing Groww MCP Client Session...")
        server_parameters = StdioServerParameters(
            command="npx",
            args=["-y", f"mcp-remote@{MCP_REMOTE_VERSION}", MCP_SERVER_URL, MCP_CALLBACK_PORT],
            env=None
        )
        try:
            self._stack = AsyncExitStack()
            read, write = await self._stack.enter_async_context(stdio_client(server_parameters))
            self.session = await self._stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
            logger.info("✅ Groww MCP Session initialized successfully!")
        except Exception as e:
            logger.error(f"❌ Failed to initialize MCP Session: {e}")
            if self._stack:
                try:
                    await self._stack.aclose()
                except Exception:
                    pass
            self.session = None
            self._stack = None
            raise

    def reconnect(self):
        """Attempt to reconnect (e.g. after token expiry). Respects circuit breaker."""
        if self._connecting:
            return
        self._connected_event.clear()
        self.session = None
        self._connect_background()

    async def _cleanup_async(self):
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception:
                pass

    def run_coroutine(self, coro):
        """Run a coroutine safely in the dedicated MCP background thread."""
        if not self.is_ready():
            # If we're not ready, attempt to reconnect
            if not self._connecting:
                self.reconnect()
                
            # Wait up to 30 seconds for connection
            if not self.wait_until_ready(timeout=30):
                logger.warning("Groww MCP not ready — returning empty result")
                return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=30)
        except Exception as e:
            logger.error(f"MCP coroutine failed: {e}")
            return None

    # --- Async implementations that must run on the dedicated loop ---
    async def _get_ltp_async(self, tickers: List[str]) -> Dict[str, float]:
        if not self.session:
            return {}
        try:
            # Groww search queries often work better without the .NS suffix
            search_queries = [t.split('.')[0] for t in tickers]
            result = await self.session.call_tool("get_ltp", arguments={"search_queries": search_queries})
            content = result.content[0].text
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                return {}
            ltp_results = data.get("result", {}).get("ltp_results", {})
            prices = {}
            for key, item in ltp_results.items():
                symbol = item.get("symbol")
                ltp = item.get("ltp")
                if symbol and ltp is not None:
                    # Map back to the requested ticker format (with or without .NS)
                    matched_ticker = next((t for t in tickers if t == symbol or t.split('.')[0] == symbol), None)
                    if matched_ticker:
                        if "NSE" in key or matched_ticker not in prices:
                            prices[matched_ticker] = float(ltp)
            return prices
        except Exception as e:
            logger.error(f"Failed to fetch LTP via MCP: {e}")
            return {}

    async def _get_historical_data_async(self, ticker: str, start_date: str, end_date: str, interval: str) -> Optional["pd.DataFrame"]:
        if not self.session:
            return None
        try:
            import pandas as pd
            result = await self.session.call_tool("fetch_historical_candle_data", arguments={
                "company_name": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "interval_in_minutes": interval,
                "segment": "CASH"
            })
            content = result.content[0].text
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                return None
            candles = data.get("result", {}).get("candles", [])
            if not candles:
                return None
            df = pd.DataFrame(candles)
            df.rename(columns={"timestamp": "Date"}, inplace=True)
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            df['ticker'] = ticker
            return df
        except Exception as e:
            logger.error(f"Failed to fetch historical data via MCP for {ticker}: {e}")
            return None

    async def _fetch_fundamentals_screener_async(self, query: str, max_results: int = 10) -> List[Dict]:
        if not self.session:
            return []
        try:
            result = await self.session.call_tool("fetch_fundamentals_screener", arguments={
                "query": query,
                "max_results": max_results
            })
            content = result.content[0].text
            try:
                data = json.loads(content)
                return data.get("result", {}).get("results", [])
            except json.JSONDecodeError:
                return []
        except Exception as e:
            logger.error(f"Failed to fetch fundamental screener via MCP: {e}")
            return []


    async def _get_open_interest_analysis_async(self, symbol: str) -> Dict:
        if not self.session:
            return {}
        try:
            result = await self.session.call_tool("get_open_interest_analysis", arguments={
                "symbol": symbol
            })
            content = result.content[0].text
            try:
                data = json.loads(content)
                return data.get("result", {})
            except json.JSONDecodeError:
                return {}
        except Exception as e:
            logger.debug(f"OI Analysis unavailable for {symbol}: {e}")
            return {}

    async def _get_historical_candlestick_patterns_async(self, ticker: str) -> str:
        if not self.session:
            return ""
        try:
            result = await self.session.call_tool("get_historical_candlestick_patterns", arguments={
                "company_name": ticker,
                "interval_in_minutes": "1440"
            })
            return result.content[0].text
        except Exception as e:
            logger.debug(f"Historical Candlestick Patterns unavailable for {ticker}: {e}")
            return ""

# --- Synchronous Wrappers ---

def get_live_prices_sync(tickers: List[str]) -> Dict[str, float]:
    client = GrowwMCPClient.get_instance()
    result = client.run_coroutine(client._get_ltp_async(tickers))
    return result or {}

def get_historical_data_sync(ticker: str, start_date: str, end_date: str, interval: str = "1440"):
    client = GrowwMCPClient.get_instance()
    return client.run_coroutine(client._get_historical_data_async(ticker, start_date, end_date, interval))

def fetch_fundamentals_screener_sync(query: str, max_results: int = 10) -> List[Dict]:
    client = GrowwMCPClient.get_instance()
    result = client.run_coroutine(client._fetch_fundamentals_screener_async(query, max_results))
    return result or []

def get_oi_analysis_sync(ticker: str) -> Dict:
    # Strip .NS to get base symbol for derivatives
    symbol = ticker.split(".")[0]
    client = GrowwMCPClient.get_instance()
    result = client.run_coroutine(client._get_open_interest_analysis_async(symbol))
    return result or {}

def get_historical_patterns_sync(ticker: str) -> str:
    client = GrowwMCPClient.get_instance()
    result = client.run_coroutine(client._get_historical_candlestick_patterns_async(ticker))
    return result or ""
