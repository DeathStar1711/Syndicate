# Handoff Report: Backend Audit & Optimization

## Observation
1. **Trailing Stop-Loss Breakdown**: In `backend/src/trading/intraday_monitor.py:71`, the trailing stop loss logic uses `conn = self.trader._get_conn()`. The `PaperTrader` class has been migrated to SQLAlchemy and no longer has this method. This raises an `AttributeError` which is caught silently by a broad `except BaseException`, causing the trailing SL logic to silently fail on every trigger.
2. **ML Probability NaN Edge Case**: In `backend/src/ml/predictor.py:124`, `bullish_prob` is calculated from model output. If the input data has extreme outliers causing scaling issues or the model is degenerate, `bullish_prob` can be `NaN`. Subsequent comparisons (`bullish_prob >= self.threshold`) and math logic will silently propagate this, eventually attempting to serialize `NaN` in JSON over API boundaries.
3. **Price Fetcher Exchange Mismatch**: In `backend/src/data/groww_feed.py:50`, the Groww ticker conversion is hardcoded to strip both `.NS` and `.BO` but always append `NSE_` prefix (`f"NSE_{symbol}"`). This causes BSE queries to fetch NSE data or fail entirely.
4. **Redundant Imports in Retry Loop**: In `backend/src/data/fetcher.py:31`, `import datetime` and `from src.data.groww_mcp import get_historical_data_sync` are placed inside the `_do_fetch` function, which is decorated with `@retry`. This means the module import mechanism is invoked repeatedly upon every fetch and retry, causing performance degradation.
5. **Portfolio Price Validation Exception**: In `backend/src/api/routes/portfolio.py:219`, the check `math.isnan(current_price)` is executed directly on the returned value. If `current_price` is an integer, this will throw a `TypeError` in older Python versions, crashing the route.
6. **Timezone Strip Exception**: In `backend/src/data/fetcher.py:144`, the condition `if df.index.tz is not None:` assumes `df.index` has a `tz` attribute. While Pandas DatetimeIndex does, some return types from yfinance in edge cases (e.g., empty dataframes converted to object types) might not, or checking `tz` instead of `tzinfo` could be unsafe depending on Pandas version.

## Logic Chain
- The `intraday_monitor.py` issue guarantees the trailing stop-loss feature does not work. Fixing it requires querying the `Trade` SQLAlchemy model.
- The `predictor.py` issue introduces systemic instability if data quality degrades. Standard ML pipelines must handle `NaN` predictions by falling back to neutral confidence.
- The `groww_feed.py` bug renders BSE tracking fundamentally broken on the real-time websocket and REST fallback.
- The redundant imports in `fetcher.py` add unnecessary overhead to a high-throughput data fetching pipeline.
- The `portfolio.py` check is an easily preventable crash. Explicitly casting `float(current_price)` before checking `math.isnan()` ensures type safety.

## Caveats
- I did not test the actual database migration scripts.
- The unoffical `growwapi` SDK might require specific formats for BSE stocks that differ from `BSE_`. The implementer should verify the correct prefix.
- The `get_historical_data_sync` is lazy loaded to avoid circular imports, but it should still be placed outside the `_do_fetch` method (e.g. at the top of `fetch_latest` body).

## Conclusion
The backend audit identified critical bugs in the trailing stop-loss execution, ML confidence calculation, and data feed routing for non-NSE symbols. These issues directly impact trade risk management and cross-exchange support.
**Fix Strategy**:
1. Refactor `intraday_monitor.py` trailing SL to use `SessionLocal` and the `Trade` model.
2. Add a `pd.isna(bullish_prob)` guard in `predictor.py` that gracefully returns the original signal.
3. Update `groww_feed.py` to check for `.BO` and apply a `BSE_` prefix instead.
4. Relocate inner loop imports in `fetcher.py` to the function scope level, outside the retry wrapper.
5. Safely cast `current_price` to float in `portfolio.py` before validation.

## Verification Method
1. Inspect `backend/src/trading/intraday_monitor.py` to ensure SQLAlchemy is used for the trailing SL update.
2. Verify `backend/src/ml/predictor.py` has a `NaN` check.
3. Check `backend/src/data/groww_feed.py` for conditional handling of `.BO`.
4. Check `backend/src/api/routes/portfolio.py` for `float(current_price)` casting.
5. Run the unit test suite `pytest backend/` after changes.
