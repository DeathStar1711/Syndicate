import { useEffect, useSyncExternalStore } from 'react';
import { subscribeWs, getWsState, initWebSocket } from '../stores/websocketStore';

export function useWebSocket() {
  const state = useSyncExternalStore(subscribeWs, getWsState);

  useEffect(() => {
    initWebSocket();
  }, []);

  return state;
}
