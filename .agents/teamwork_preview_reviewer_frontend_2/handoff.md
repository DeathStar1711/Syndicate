# Handoff Report: Frontend Fixes Review

## 1. Observation
- In `TradingViewChart.tsx`, the component conditionally returns `<div>Error: {error}</div>` when `error` is true (lines 133-135).
- This completely unmounts the `<div ref={chartContainerRef} />` element.
- The `useEffect` that initializes the chart and clears the error (via `setError(null)`) begins with `if (!chartContainerRef.current) return;` (line 42).

## 2. Logic Chain
1. If the chart creation throws an error, the `catch` block calls `setError(e.message)`.
2. The component re-renders and conditionally returns the error div, unmounting the original `chartContainerRef` element.
3. If the parent component passes new, valid `data` props to the chart, the `useEffect` is triggered again.
4. Because the original container was unmounted, `chartContainerRef.current` is `null`.
5. The `useEffect` returns immediately at line 42, skipping `setError(null)` and the chart recreation logic entirely.
6. The component is permanently locked in the error state and can never recover.

## 3. Caveats
- The changes made to `websocketStore.ts`, `dataCache.ts`, and `api.ts` are robust and correctly implemented. The global state fix effectively resolves the multiple websocket bug without memory leaks, and `getEntry` reference equality resolves React rerender loops.

## 4. Conclusion
- The backend/logic fixes are excellent, but the error handling logic in `TradingViewChart.tsx` introduces a permanent lockup bug upon error.
- **Verdict**: REQUEST_CHANGES.

## 5. Verification Method
- Pass an empty or invalid dataset to `TradingViewChart` to trigger the `catch` block.
- Pass a valid dataset to the component afterward.
- Observe that the chart remains stuck displaying the error text instead of rendering the valid data.

## Review Summary
**Verdict**: REQUEST_CHANGES

### Findings
- **[Major] Permanent Error Lockup in TradingViewChart**: When an error is caught, the component unmounts its main container. Subsequent prop changes fail to clear the error because the `useEffect` requires the container ref to exist.
- **Suggestion**: Keep the `chartContainerRef` element mounted. Either hide it using CSS (`display: error ? 'none' : 'block'`) while showing the error, or use a separate `useEffect` to clear the error state when `data` changes before the main chart effect runs.
