# Backend Codebase Audit & Optimization Report

## 1. Observation
- **API (Signals History Loss)**: In `backend/src/api/routes/signals.py`, the `_save_signals_to_db` function calls `db.query(Signal).delete()` before inserting new signals.
- **DB Interaction (Missing Method)**: In `backend/src/trading/intraday_monitor.py`, the trailing stop loss logic calls `conn = self.trader._get_conn()`. However, `PaperTrader` in `backend/src/trading/paper_trader.py` does not define `_get_conn`.
- **DB Interaction (Capital Race Condition)**: In `backend/src/trading/paper_trader.py`, `close_trade` calculates `new_capital` and updates `PortfolioState` outside of the primary transaction, using a read-then-write sequence.
- **Performance (Synchronous MCP Calls)**: In `backend/src/strategy/signals.py`, `generate_signals` iterates over all `tickers` and sequentially calls `get_oi_analysis_sync(ticker)`, which makes a blocking network request via the Groww MCP server.
- **API (WebSocket Feed Crash)**: In `backend/src/data/groww_feed.py`, `GrowwFeedListener.connect_and_listen` instantiates `ws = GrowwFeed(token=self.client.token)`. However, `GrowwDataClient._authenticate()` does not assign `self.token` as an attribute.
- **Performance (SQLite Overload/Locking)**: `backend/src/db/session.py` does not enable `WAL` mode. `backend/src/data/tick_recorder.py` opens and closes a new `sqlite3.connect` for every single tick. `backend/src/trading/intraday_monitor.py` executes a DB query (`self.trader.get_open_positions()`) inside the `on_tick` callback for every tick.

## 2. Logic Chain
1. **History Loss**: Deleting all signals during generation defeats the purpose of the `Signal` table. Downstream endpoints querying `Signal.date.desc()` expect historical continuity but will only ever find the most recent run.
2. **Trailing Stop Failure**: When the intraday monitor detects a condition to raise the trailing stop loss, the missing `_get_conn()` method raises an `AttributeError`. The `except BaseException:` block swallows this, meaning trailing stops simply silently fail to apply.
3. **Capital Leak**: Because `close_trade` does not lock the `PortfolioState` row when calculating `current_capital`, concurrent trades closing at exactly the same time (common during intraday spikes) will overwrite each other's capital calculations, leading to permanent capital drift.
4. **Signal Generation Bottleneck**: Calling a blocking network coroutine sequentially inside a loop over hundreds of tickers transforms an `O(N)` local process into a multi-minute API bottleneck, severely hanging the FastApi background thread.
5. **Feed Initialization Failure**: Referencing `self.client.token` raises an `AttributeError` during WebSocket initialization, meaning the live feed monitor never starts.
6. **Database Lockup**: Opening/closing connections per tick and running SELECT queries on the main trade DB multiple times a second per ticker will overwhelm SQLite. Without WAL (Write-Ahead Logging), writes block reads, inevitably causing `database is locked` exceptions under concurrent load.

## 3. Caveats
- I did not test the external tools (Groww MCP) or models live, so I am inferring the length of network delays, though synchronous requests in loops are universally slow.
- The `growwapi` module's actual internal structure isn't fully visible, but standard Python attribute access rules confirm the missing `token` bug.
- I assumed a high volume of tickers (e.g., Nifty 50 or 500) based on typical trading systems; for a 2-ticker watchlist, the performance bottlenecks might be masked but still exist architecturally.

## 4. Conclusion
The backend architecture is fundamentally unstable for concurrent, intraday trading.
**Recommended Fix Strategy:**
1. **Signals**: Remove `db.query(Signal).delete()` to preserve history. Filter by `date` strictly when querying.
2. **Trailing Stops**: Update `intraday_monitor.py` to use `SessionLocal` for updating `stop_loss` instead of the non-existent `_get_conn()`.
3. **Capital Tracking**: Refactor `close_trade` to compute and execute an atomic update (e.g., `UPDATE portfolio_state SET value = value + :delta`) within the main transaction.
4. **Network Calls**: Refactor `strategy/signals.py` to use `asyncio.gather` for fetching `oi_data` concurrently before the pandas computation loop.
5. **Feed Listener**: Save `self.token = token` in `GrowwDataClient._authenticate()`.
6. **SQLite Scaling**: Enable `PRAGMA journal_mode=WAL;` in `db/session.py`. Batch DB writes in `TickRecorder` using an in-memory queue instead of per-tick `connect()`. Cache open positions in `intraday_monitor.py` and update the cache dynamically instead of querying the DB per tick.

## 5. Verification Method
- **Signals**: Inspect `backend/src/api/routes/signals.py:18` for `delete()`.
- **Trailing Stop**: Search for `_get_conn` in `backend/src/trading/paper_trader.py` (it doesn't exist).
- **Feed Token**: Inspect `backend/src/data/groww_feed.py:31` vs `line 72`.
- **Tick Recorder**: Inspect `backend/src/data/tick_recorder.py:39` where `sqlite3.connect` is instantiated inside the `record_tick` method.
- **Run the API tests**: Run `pytest backend/tests/` (if tests are written for these flows) and watch the SQLite locks and trailing stop loss failures in the logs.
