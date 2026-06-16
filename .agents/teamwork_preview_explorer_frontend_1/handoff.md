# Handoff Report: Frontend Audit & Optimization

## 1. WebSocket Zombie Leak (Long-Term Stability Bug)
**Observation:**
In `src/hooks/useWebSocket.ts`, the `useEffect` cleanup function clears the `reconnectTimer` and then calls `wsRef.current?.close()`. However, the `ws.onclose` event handler unconditionally sets a new `setTimeout` to `connect()` again after 3 seconds:
```typescript
// useWebSocket.ts:43
ws.onclose = () => {
  setConnected(false);
  // Auto-reconnect after 3s
  reconnectTimer.current = window.setTimeout(connect, 3000);
};
```
Because `useWebSocket` is used in multiple route components (`Signals.tsx`, `Portfolio.tsx`, `Settings.tsx`), navigating between pages unmounts the component and triggers the cleanup. The `onclose` handler fires *after* cleanup and creates a new connection loop since it doesn't check if the component is still mounted.

**Logic Chain:**
1. User navigates to `/signals` -> `useWebSocket` mounts, creates WebSocket A.
2. User navigates to `/portfolio` -> `Signals` unmounts. Cleanup clears timer and closes WebSocket A.
3. `Portfolio` mounts, creates WebSocket B.
4. WebSocket A's `onclose` fires asynchronously -> sets a timeout to run `connect()` -> creates zombie WebSocket C.
5. As the user navigates, the number of zombie WebSockets grows exponentially, flooding the backend and browser network stack.

**Conclusion:**
There is a severe memory leak and connection spam bug. The hook needs an `isMounted` or `intentionalClose` ref to prevent `onclose` from reconnecting if the component was unmounted.

**Verification Method:**
1. Add a `console.log("WS connected")` in `useWebSocket`.
2. Navigate between Dashboard, Signals, and Portfolio repeatedly.
3. Observe the console or browser Network tab showing an increasing number of concurrent active WebSockets.

---

## 2. WebSocket Global Re-render (Performance Bottleneck)
**Observation:**
In `src/App.tsx`, the root layout uses the WebSocket hook: `const { connected } = useWebSocket();`
Inside `useWebSocket.ts`, it maintains local React state for prices:
```typescript
// useWebSocket.ts:37
if (msg.type === 'price_update' && typeof msg.data === 'object') {
  setPrices(prev => ({ ...prev, ...(msg.data as Record<string, number>) }));
}
```

**Logic Chain:**
1. `App.tsx` calls `useWebSocket()`, creating a hook instance with its own `prices` state.
2. When the backend broadcasts a `price_update` (which happens frequently during market hours), `setPrices` is called inside `App`'s hook instance.
3. This state update forces `App` to re-render.
4. Because `App` has no `React.memo` around its children (`Sidebar`, `TopBar`, `Routes`), the *entire React component tree* re-renders on every single price tick.

**Conclusion:**
This will cause significant CPU usage and UI lag during active market hours. The WebSocket connection and price state should be lifted out of React state into a global store (like `dataCache.ts` or `pipelineStore.ts` using `useSyncExternalStore`), so components only re-render if they explicitly subscribe to price updates.

**Verification Method:**
Add a `console.log("App rendered")` inside `App.tsx`. Send a mock `price_update` via the WebSocket server. Observe that the entire app re-renders.

---

## 3. Double Caching & Stale UI Data (Edge Cases)
**Observation A (Double Caching):**
`src/services/api.ts` implements internal caching for briefings and sectors:
```typescript
// api.ts:63
async getMarketBriefing() {
  if (this._briefingCache && Date.now() - this._briefingCacheTime < 3600000) {
    return this._briefingCache;
  }
...
```
However, `src/pages/Dashboard.tsx` consumes this using `useCachedApi`, which already provides stale-while-revalidate caching.

**Observation B (Stale TopBar):**
`src/components/layout/TopBar.tsx` fetches index data using `useApi` with empty dependencies:
```typescript
// TopBar.tsx:12
const { data } = useApi<MarketStatus>(() => api.getMarketStatus(), []);
```

**Logic Chain:**
- For **A**: If a background process or manual user action (via `Settings.tsx`) invalidates the `useCachedApi` store for 'briefing', the hook tries to fetch fresh data. But `api.getMarketBriefing()` instantly returns its internal stale `_briefingCache`, completely defeating the cache invalidation mechanism.
- For **B**: Because `TopBar` sits in `App.tsx` and never unmounts, the empty dependency array means `getMarketStatus` runs exactly once. The NIFTY/SENSEX prices and `current_time` will remain frozen forever until a hard page reload.

**Conclusion:**
Remove the internal caches (`_briefingCache`, `_sectorsCache`) from `api.ts` and let `useCachedApi` manage caching. Convert `TopBar.tsx` to use `useCachedApi` with a short `staleMs` or a `setInterval` so the market indices actually update.

**Verification Method:**
1. Trigger a manual "Market Briefing" run from `Settings.tsx`. Observe that `Dashboard.tsx` does not show the updated text until 1 hour passes or the page is hard-reloaded.
2. Leave the dashboard open for 5 minutes; observe that the NIFTY price in the TopBar never changes.

## Caveats
- I did not test the actual backend WebSocket server; my findings are based on static analysis of the React lifecycle and state dependencies.
- Changes to `useWebSocket` to make it a global store might require refactoring `Portfolio.tsx` and `Signals.tsx`.

## Remaining Work
- Implement a singleton WebSocket manager (using `useSyncExternalStore` or a context provider).
- Add an `isMounted` safeguard to `useWebSocket` if a singleton is not adopted immediately.
- Remove hardcoded caches from `api.ts`.
- Update `TopBar.tsx` to poll or use WebSocket for index prices.
