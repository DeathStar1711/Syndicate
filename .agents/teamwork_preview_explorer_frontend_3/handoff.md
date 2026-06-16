# Handoff Report: Frontend Audit & Optimization

## 1. Observation
- **WebSocket Reconnection Leak (`useWebSocket.ts:43-48, 56-59`)**: The cleanup function in `useWebSocket` calls `ws.close()`. This triggers the `onclose` event handler, which unconditionally schedules a reconnect via `setTimeout(connect, 3000)`.
- **Redundant WebSocket Connections (`App.tsx`, `Signals.tsx`, `Portfolio.tsx`, `Settings.tsx`)**: `useWebSocket` instantiates a new WebSocket connection each time it is used, rather than sharing a global connection.
- **Pipeline State Loss (`Signals.tsx:148`)**: The WebSocket listener for pipeline updates is scoped inside the `Signals` component. 
- **Global Re-render Bottleneck (`App.tsx:12`, `useWebSocket.ts:37-39`)**: `App.tsx` calls `useWebSocket()` to pass the `connected` status to `TopBar`. However, `useWebSocket` updates its internal `prices` state whenever a `price_update` is received. 
- **Broken Background Refresh (`dataCache.ts:121-131`)**: `useCachedApi` calculates `isStale` and sets `shouldFetch` during the component render cycle. It uses a `useEffect` to trigger the fetch if `shouldFetch` is true, but does not use a timer (like `setTimeout`) to force a re-render when the `staleMs` threshold is reached.
- **DOM Mutation in React Component (`TradingViewChart.tsx:124-126`)**: In the `catch` block for chart creation, the code directly mutates `chartContainerRef.current.innerHTML` to display an error message.

## 2. Logic Chain
1. **Critical Memory Leak**: When a user leaves a page using `useWebSocket` (e.g., navigating from Signals to Portfolio), the component unmounts and calls `ws.close()`. The `onclose` handler fires, circumventing the cleanup's `clearTimeout`, and sets a new timer to reconnect. The unmounted component connects a phantom WebSocket 3 seconds later, causing connections to multiply endlessly as the user navigates, crippling frontend and backend performance.
2. **Architecture Flaw (Redundant Connections)**: Because the WebSocket isn't a global singleton, a user viewing the `Signals` page will have multiple concurrent WebSocket connections open (one from `App`, one from `Signals`), receiving duplicate data.
3. **Pipeline State Loss**: The comment in `Signals.tsx` claims to "always process pipeline steps regardless of which page the user is viewing", but because the WebSocket listener is bound to the `Signals` component's lifecycle, navigating to another page unmounts the listener. Pipeline generation events will be permanently missed.
4. **Severe Re-render Bottleneck**: Because `useWebSocket` updates `prices` state on every price tick, and because this hook is called at the root `App` component, every price update forces the entire application React tree (Sidebar, Topbar, active page) to re-render. In a trading app with frequent ticks, this will destroy UI performance.
5. **Background Refresh Failure**: The `useCachedApi` advertises "refreshes in background", but since `isStale` is only evaluated when React natively re-renders the component, the cache will never auto-refresh while the user is idle on a page (unless the aforementioned global re-render bug accidentally triggers it).
6. **React DOM Desync**: Directly mutating `innerHTML` on a ref managed by React (`TradingViewChart`) breaks React's virtual DOM reconciliation and will cause exceptions if the component later tries to unmount or update.

## 3. Caveats
- I did not run a live backend to measure the exact performance hit of the global re-renders, but standard React rendering behavior guarantees this is a massive bottleneck.
- The `useCachedApi` reference equality bug (`getEntry` returning a new object when the cache is empty) was analyzed but deemed low-impact since keys are fetched immediately on mount, so it was excluded from the main report.

## 4. Conclusion
The frontend suffers from critical WebSocket architectural flaws that lead to infinite connection leaks, lost pipeline states, and global application re-rendering on every price tick. The custom data cache also fails to perform its advertised background refreshes. These issues must be resolved by:
1. Converting the WebSocket connection to a global singleton (outside the React tree, similar to `dataCache.ts`).
2. Moving pipeline WebSocket listening to a global scope (e.g., inside `pipelineStore.ts`).
3. Adding a `setTimeout` inside `useCachedApi` to force a background fetch when `staleMs` expires.
4. Using React state for error rendering in `TradingViewChart.tsx` rather than `innerHTML`.

## 5. Verification Method
- **WebSocket Leak**: Open the app, navigate back and forth between "Signals" and "Portfolio" 5 times. Open the browser Network tab (WS filter) and observe 5+ active WebSocket connections remaining open.
- **Global Re-render**: Add a `console.log("App rendered")` in `App.tsx`. Send a mock `price_update` WebSocket message and observe the log firing.
- **Pipeline Loss**: Start signal generation, immediately navigate to "Dashboard", wait 10 seconds, return to "Signals", and observe that the pipeline log missed all intermediate events.
