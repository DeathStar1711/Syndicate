# Frontend Codebase Investigation Report

## Core Findings Summary
The frontend architecture contains several critical bugs that cause memory leaks, connection multiplication, stale data presentation, and potential infinite rendering loops. These issues reside primarily in the API layer, global state management, and WebSocket hooks.

---

## 1. WebSocket Reconnection Memory Leak (Connection Multiplier)

### Observation
In `frontend/src/hooks/useWebSocket.ts`, the hook creates a new `WebSocket` instance every time it is mounted. In the `useEffect` cleanup function, it calls `wsRef.current?.close()`. However, `close()` asynchronously triggers the `ws.onclose` event handler. The `onclose` handler is currently set to:
```typescript
ws.onclose = () => {
  setConnected(false);
  reconnectTimer.current = window.setTimeout(connect, 3000);
};
```

### Logic Chain
1. When a component using `useWebSocket` unmounts (e.g., navigating from Signals to Portfolio), the `useEffect` cleanup clears the timeout and calls `ws.close()`.
2. The asynchronous `close` event fires shortly after, triggering the `onclose` handler *after* the component has unmounted.
3. The `onclose` handler executes and sets a new timeout to call `connect()`, which creates a brand new "ghost" WebSocket connection.
4. Because the component is already unmounted, its cleanup function will never run again, leaving the connection permanently active.
5. Every time the user navigates between pages (`App`, `Signals`, `Portfolio`, `Settings`), a new ghost connection is left behind.

### Conclusion
Navigating between pages exponentially multiplies the number of active WebSocket connections, draining client/server resources and causing redundant state updates. The `onclose` handler must be nullified in the cleanup function before calling `.close()`.

### Verification Method
1. Open the application and navigate between "Signals" and "Portfolio" 10 times.
2. Check the browser Network tab (WS filter) or backend logs (`WebSocket connected`); you will see 10+ active connections instead of 1.

---

## 2. Missing HTTP Error Handling Causing Component Crashes

### Observation
In `frontend/src/services/api.ts`, several fetch methods (e.g., `getSignals`, `getPortfolio`, `getMarketStatus`) do not verify if `res.ok` before returning `res.json()`.
```typescript
async getSignals() {
  const res = await fetch(`${API_BASE}/api/signals`);
  return res.json();
}
```

### Logic Chain
1. The `fetch` API does not throw an error for HTTP 4xx or 5xx responses unless there is a network failure.
2. If the backend returns a 500 Internal Server Error with JSON (e.g., `{"detail": "Internal Server Error"}`), `res.json()` successfully parses it.
3. `useCachedApi` treats this as a successful fetch, clearing the error state and setting `data = {"detail": "Internal Server Error"}`.
4. UI components expecting an array (e.g., `data.map(...)`) will crash entirely.

### Conclusion
Most API calls lack status code validation, leading to potential unhandled frontend crashes. All fetch wrappers must check `!res.ok` and throw an error with the parsed detail message.

### Verification Method
1. Force the backend `/api/signals` to return a 500 error.
2. Observe the React app crashing with `data.map is not a function` instead of displaying a graceful error state.

---

## 3. Stale Market Status and Frozen Clock

### Observation
In `frontend/src/components/layout/TopBar.tsx`, the market status and current time are fetched using:
```typescript
const { data } = useApi<MarketStatus>(() => api.getMarketStatus(), []);
```

### Logic Chain
1. The dependency array `[]` ensures `getMarketStatus` is only called once when `TopBar` mounts.
2. Since `TopBar` is rendered in `App.tsx` outside of the page routing, it never unmounts during a session.
3. The "Current Time", "Market Open/Closed", and NIFTY/SENSEX indices will never update without a full page refresh. The backend WebSocket implementation (`websocket.py`) does not broadcast market status.

### Conclusion
The TopBar displays stale data indefinitely. It must either implement a polling mechanism (e.g., `setInterval` to fetch every 60s) or the backend must broadcast market status via WebSockets.

### Verification Method
1. Open the app and observe the time in the TopBar.
2. Wait 5 minutes; the time will not change.

---

## 4. Un-invalidatable Frontend Static Caches

### Observation
In `frontend/src/services/api.ts`, `getMarketBriefing` caches data statically for 1 hour:
```typescript
if (this._briefingCache && Date.now() - this._briefingCacheTime < 3600000) {
  return this._briefingCache;
}
```
In `frontend/src/pages/Settings.tsx`, the user can manually trigger a new Market Briefing task via `api.runTask('market_briefing')`.

### Logic Chain
1. When the user manually triggers the `market_briefing` task, the backend successfully generates a new briefing.
2. However, there is no logic exposed to clear `api._briefingCache` or `dataCache('briefing')`.
3. When the user returns to the Dashboard, the UI still displays the old briefing until the 1-hour timer expires.

### Conclusion
Manual triggers do not reflect in the UI due to stale static variables. The `api.ts` module must expose methods to invalidate these specific caches.

### Verification Method
1. Generate a manual Market Briefing from the Settings page.
2. Return to the Dashboard and note that the briefing text has not updated.

---

## 5. `useSyncExternalStore` Infinite Loop Risk in Cache

### Observation
In `frontend/src/stores/dataCache.ts`, the snapshot getter returns a new object literal if the key doesn't exist:
```typescript
function getEntry<T>(key: string): CacheEntry<T> {
  return (cache.get(key) as CacheEntry<T>) ?? {
    data: null, fetchedAt: 0, isFetching: false, fetchId: 0, error: null
  };
}
```

### Logic Chain
1. React's `useSyncExternalStore` requires `getSnapshot` to return the *exact same object reference* unless the underlying state has changed.
2. Because `getEntry` returns a new `{ data: null... }` literal every time it is called for an uninitialized key, React detects a state change on every evaluation.
3. This can trigger "Maximum update depth exceeded" warnings or infinite re-render loops in strict/concurrent mode before the first fetch populates the cache.

### Conclusion
The cache must mutate the Map to insert the default object upon first access rather than returning a transient literal.

### Verification Method
Inspect the `getEntry` function in `dataCache.ts` and verify it does not assign the default object to the `cache` Map before returning.

---

## Caveats
- I did not verify the backend LLM/ML implementation logic, as the scope was strictly frontend architecture and stability.
- The WebSocket issue assumes that `close()` fires the event asynchronously, which is standard browser behavior. Testing this in a live browser environment is the definitive verification.
