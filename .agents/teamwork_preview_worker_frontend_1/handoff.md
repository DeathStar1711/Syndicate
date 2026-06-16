# Handoff Report: Frontend Audit & Fixes

## 1. Observation
- `useWebSocket.ts` created an unbound loop with `onclose` automatically reconnecting. No global state meant multiple components created multiple WebSockets.
- `api.ts` used static properties for caching `briefing` and `sectors` independently of standard caching, and lacked HTTP error handling `!res.ok`.
- `TopBar.tsx` fetched `MarketStatus` once and never polled for changes.
- `dataCache.ts` returned a new object literal `{ data: null, ... }` on missing cache misses, breaking React's reference equality for `useSyncExternalStore`.
- `TradingViewChart.tsx` injected `<div style="color: red...` directly into `chartContainerRef.current.innerHTML`.

## 2. Logic Chain
- **WebSocket**: Created `src/stores/websocketStore.ts` to hold a singleton connection and handle the global pipeline step events. Modified `useWebSocket.ts` to `useSyncExternalStore` so multiple hooks use the same socket instance without leaking connections.
- **API Cache & Error Handling**: Stripped manual static caching variables from `api.ts`. Added `if (!res.ok) throw new Error(...)` to all fetch wrappers to catch backend errors rather than trying to parse JSON errors as legitimate data.
- **TopBar Polling**: Replaced `useApi` with `useCachedApi` in `TopBar.tsx` configuring a `60_000` ms staleness. 
- **Cache Fix**: Modified `getEntry` in `dataCache.ts` to immediately `.set()` the default object in the map if it doesn't exist, preserving reference equality. Re-implemented background fetching via a `setInterval` that verifies staleness.
- **TradingView Chart**: Used `React.useState` for error logging. Replaced `innerHTML` assignment with an explicit conditional error return component.

## 3. Caveats
- No new UI elements were added for TopBar polling. It simply leverages existing background updates.
- The `useCachedApi` interval polling checks globally every min(10s, staleMs). This runs constantly while components using the cache are mounted.

## 4. Conclusion
- The frontend memory leaks, multiple WS connections, missing error catches, DOM mutations, and state management rendering loops are resolved.

## 5. Verification Method
- Execute `npm run build` in the `frontend` directory to ensure TS builds successfully.
- Manually run `npm run dev` and navigate the dashboard, check network tab to verify single WebSocket connection.

Remaining Work: none.
