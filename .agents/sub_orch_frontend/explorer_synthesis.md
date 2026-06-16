# Frontend Audit & Optimization - Explorer Synthesis

## Consensus
1. **WebSocket Reconnection Leak**: `useWebSocket.ts` creates new ghost connections on unmount because `onclose` fires after cleanup and unconditionally schedules `connect()`.
2. **Global WebSocket State Bottleneck**: `App.tsx` calls `useWebSocket()` which maintains `prices` in local state. Every price update re-renders the entire application tree. Additionally, multiple components using `useWebSocket` create multiple duplicate connections.
3. **Stale UI Data (TopBar & API Caches)**:
   - `api.ts` hardcodes caching (`_briefingCache`, `_sectorsCache`), ignoring cache invalidations.
   - `TopBar.tsx` fetches `MarketStatus` once (`useApi` with `[]` dependency) and never updates.
4. **Cache Reference Equality**: `dataCache.ts` `getEntry` returns a new object literal if a key doesn't exist, which breaks `useSyncExternalStore` reference equality.
5. **Missing HTTP Error Handling**: Fetch calls in `api.ts` do not check `!res.ok`, returning JSON error payloads that crash components.
6. **Pipeline State Loss**: WebSocket pipeline listeners are bound to the `Signals` component, meaning background updates are lost when the user navigates away.
7. **React DOM Desync**: `TradingViewChart.tsx` mutates `innerHTML` for error handling.

## Required Fixes (Worker Tasks)
1. **Global WebSocket Singleton**: Refactor WebSocket management into a global store (e.g., in a new `websocketStore.ts` or modifying `useWebSocket.ts` to use a singleton outside React state) using `useSyncExternalStore` or similar. Prevent the memory leak by ensuring `onclose` does not reconnect if disconnected intentionally, and ensure only one connection exists globally. Move the pipeline listener to this global store so state isn't lost.
2. **API Caches & Error Handling**: Remove `_briefingCache` and `_sectorsCache` from `api.ts`. In all `api.ts` fetch wrappers, add `if (!res.ok) throw new Error(...)` before returning `res.json()`.
3. **TopBar Polling**: Update `TopBar.tsx` to poll for market status periodically or consume it from the WebSocket if available.
4. **Fix `dataCache.ts`**: Update `getEntry` to set and return the default object in the cache map if it doesn't exist, preserving object reference equality. Fix the background refresh mechanism.
5. **Fix `TradingViewChart.tsx`**: Remove direct `innerHTML` DOM mutation and use standard React state for error rendering.
