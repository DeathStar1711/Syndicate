# Backend Audit & Optimization Handoff

## 1. Observation
- **N+1 Network & MCP Calls**: In `src/strategy/signals.py` (`generate_signals`), there is a loop over `data.items()` calling `get_oi_analysis_sync(ticker)`. In `src/llm/signal_validator.py` (`batch_validate_signals`), there is a loop over `signals` calling `yf.Ticker(ticker).info` and redundantly calling `get_oi_analysis_sync` and `get_historical_patterns_sync`.
- **Missing Timeouts**: In `src/data/market_context.py`, `yf.download(tickers, period=period, progress=False)` does not have a timeout.
- **SQLite Concurrency Bottleneck**: In `src/db/session.py`, `create_engine` connects to `portfolio.db` without enabling `WAL` (Write-Ahead Logging) mode (`PRAGMA journal_mode=WAL;`).
- **Broad Exception Masking**: In `src/api/websocket.py`, `broadcast` silently drops connections on any exception during `send_json` without logging. `src/llm/tools.py` ignores exceptions in `_resolve_company_name`.
- **Blocking Sleeps**: `time.sleep(2.0)` is used synchronously in `src/llm/tools.py` (`_search_ddg`), which blocks execution threads.

## 2. Logic Chain
1. The N+1 synchronous calls inside the loops mean that if the watchlist contains 50-100 tickers, the backend will sequentially execute hundreds of network requests and MCP tool calls. This blocks the signal generation pipeline, drastically reducing performance and causing timeouts.
2. The redundant call to `get_oi_analysis_sync` in the LLM validator doubles the wait time unnecessarily since the data could be passed from the initial fetch.
3. Without a timeout on `yf.download`, network hiccups to Yahoo Finance will indefinitely block the `MLPredictor` initialization and thus the entire strategy engine.
4. SQLite's default rollback journal mode locks the entire database for writes. Concurrent API requests and background tasks (like `_run_signal_generation`) will hit `database is locked` errors under load. Enabling `WAL` mode allows concurrent readers and writers.
5. Masking exceptions in the WebSocket broadcaster hides critical bugs like `TypeError` or `JSONDecodeError`, masquerading them as client disconnections.

## 3. Caveats
- I did not test the exact execution time of the Groww MCP calls, but sequential IPC calls inherently take hundreds of milliseconds each.
- The `time.sleep` calls might be harmless if executed strictly in background worker threads, but they will lock up FastAPI worker threads if called synchronously in an API request path.
- I haven't evaluated the accuracy of the ML models or the technical indicators. The audit strictly targeted system performance and stability.

## 4. Conclusion
The backend is fundamentally single-threaded in its data ingestion and external tool calls, creating massive bottlenecks. 
- **Fix Strategy 1**: Refactor data ingestion loops in `src/strategy/signals.py` and `src/llm/signal_validator.py` to use `asyncio.gather` for concurrent MCP and network calls. Pass down fetched data instead of refetching.
- **Fix Strategy 2**: Set timeouts for all `yfinance` and external API requests (e.g., `timeout=10`).
- **Fix Strategy 3**: Add `PRAGMA journal_mode=WAL;` to the SQLite engine connection in `src/db/session.py` to prevent locking.
- **Fix Strategy 4**: Log actual error messages in `except Exception:` blocks, especially in the WebSocket manager, to aid future debugging.

## 5. Verification Method
- **N+1 Fix**: Run `pytest` and time the signal generation command. Replace the loop with `asyncio.gather` and observe the duration drop from minutes to seconds.
- **SQLite Concurrency**: Write a short test script that spins up 10 threads reading/writing to `portfolio.db` to trigger the `database is locked` error, then verify `WAL` mode resolves it.
- **Timeouts**: Temporarily block the network or use toxiproxy and verify that `yf.download` gracefully times out rather than hanging.
