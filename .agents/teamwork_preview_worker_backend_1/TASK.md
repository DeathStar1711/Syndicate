# Backend Audit & Optimization Fix Plan

The Explorer team has completed their audit of `backend/src/` and found the following critical issues. You must implement the fixes for all of them, verify with tests, and report back.

## 1. Trading Logic & State
- **Trailing Stop-Loss**: `backend/src/trading/intraday_monitor.py` uses `self.trader._get_conn()`, which doesn't exist. Update it to use `SessionLocal` to update the `stop_loss`.
- **Capital Leak Race Condition**: In `backend/src/trading/paper_trader.py`, `close_trade` computes and updates `PortfolioState` capital outside a locked transaction using read-then-write. Refactor to compute and execute an atomic update (e.g., `UPDATE portfolio_state SET value = value + :delta`) within the main transaction.
- **Open Positions Query per Tick**: In `backend/src/trading/intraday_monitor.py`, `self.trader.get_open_positions()` is queried on every tick. Cache open positions and update dynamically.

## 2. API & Data Feeds
- **Signals History Loss**: In `backend/src/api/routes/signals.py`, `_save_signals_to_db` deletes all existing signals. Remove `db.query(Signal).delete()` to preserve history. Filter by date instead.
- **WebSocket Feed Crash**: In `backend/src/data/groww_feed.py`, `GrowwDataClient._authenticate()` does not save the token (`self.token = token`), causing feed initialization to crash.
- **Price Fetcher Exchange Mismatch**: In `backend/src/data/groww_feed.py`, the ticker conversion strips `.BO` but always appends `NSE_`. Check for `.BO` and apply `BSE_` prefix instead.
- **Portfolio Type Safety**: In `backend/src/api/routes/portfolio.py`, safely cast `current_price` to `float(current_price)` before checking `math.isnan(current_price)`.

## 3. Machine Learning
- **NaN Probability Edge Case**: In `backend/src/ml/predictor.py`, `bullish_prob` can be `NaN`. Add a `pd.isna(bullish_prob)` guard that gracefully handles it (returns the original signal/neutral confidence).

## 4. Performance & DB Locking
- **N+1 MCP Calls**: In `backend/src/strategy/signals.py` (`generate_signals`) and `backend/src/llm/signal_validator.py`, synchronous network/MCP calls in loops cause bottlenecks. Refactor to use `asyncio.gather` for fetching concurrently.
- **Redundant Imports**: In `backend/src/data/fetcher.py`, imports inside `_do_fetch` retry loop degrade performance. Move them out of the retry wrapper.
- **Missing Network Timeouts**: In `backend/src/data/market_context.py`, `yf.download` is missing a timeout. Add a timeout (e.g., `timeout=10`).
- **SQLite Missing WAL**: In `backend/src/db/session.py`, `create_engine` lacks `WAL` mode. Execute `PRAGMA journal_mode=WAL;` on connect.
- **SQLite Per-Tick Connection**: In `backend/src/data/tick_recorder.py`, `sqlite3.connect` is called inside `record_tick`. Batch writes using an in-memory queue or reuse connection.

## 5. Error Handling
- **Broad Exception Masking**: In `backend/src/api/websocket.py` (`broadcast`), log exceptions during `send_json` instead of silently dropping. Same in `src/llm/tools.py` (`_resolve_company_name`).
- **Timezone Exception**: In `backend/src/data/fetcher.py`, checking `df.index.tz` safely.
- **Blocking Sleeps**: Synchronous `time.sleep` in `src/llm/tools.py` (`_search_ddg`) might block threads.

**MANDATORY INTEGRITY WARNING**
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Run `pytest backend/` after changes. Provide a handoff report in your directory when done.
