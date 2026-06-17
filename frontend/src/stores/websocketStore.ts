import { api } from '../services/api';
import {
  addPipelineStep,
  setShowLog as pipelineSetShowLog,
  finishGeneration,
  type PipelineStep,
} from './pipelineStore';
import { invalidateCache } from './dataCache';

export type WsMessage = {
  type: string;
  data: unknown;
};

type WsState = {
  connected: boolean;
  lastMessage: WsMessage | null;
  prices: Record<string, number>;
};

let state: WsState = {
  connected: false,
  lastMessage: null,
  prices: {},
};

let ws: WebSocket | null = null;
let reconnectTimer: number | undefined;
let intentionalClose = false;

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) {
    listener();
  }
}

export function connectWs() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;

  try {
    const currentWs = new WebSocket(api.getWsUrl());
    ws = currentWs;
    let ping: ReturnType<typeof setInterval>;

    currentWs.onopen = () => {
      if (ws !== currentWs) return;
      state = { ...state, connected: true };
      notify();
      ping = setInterval(() => {
        if (currentWs.readyState === WebSocket.OPEN) {
          currentWs.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    currentWs.onmessage = (event) => {
      if (ws !== currentWs) return;
      try {
        const msg: WsMessage = JSON.parse(event.data);
        state = { ...state, lastMessage: msg };

        if (msg.type === 'price_update' && typeof msg.data === 'object') {
          state = {
            ...state,
            prices: { ...state.prices, ...(msg.data as Record<string, number>) }
          };
        }

        // Pipeline listener logic (moved from Signals.tsx)
        if (msg.type === 'pipeline_step') {
          const step = msg.data as PipelineStep;
          addPipelineStep(step);
          pipelineSetShowLog(true);

          if (step.step === 'Pipeline Complete' || step.step === 'Pipeline Error') {
            finishGeneration();
            invalidateCache('signals');
          }
        }

        if (msg.type === 'signals_updated') {
          finishGeneration();
          invalidateCache('signals');
        }

        notify();
      } catch { /* ignore malformed */ }
    };

    currentWs.onclose = () => {
      clearInterval(ping);
      if (ws === currentWs) {
        state = { ...state, connected: false };
        notify();
        ws = null;

        if (!intentionalClose) {
          clearTimeout(reconnectTimer);
          reconnectTimer = window.setTimeout(connectWs, 3000);
        }
      }
    };

    currentWs.onerror = () => {
      if (ws !== currentWs) return;
      currentWs.close();
    };
  } catch {
    state = { ...state, connected: false };
    notify();
  }
}

export function initWebSocket() {
  if (!ws) {
    intentionalClose = false;
    connectWs();
  }
}

export function closeWebSocket() {
  intentionalClose = true;
  clearTimeout(reconnectTimer);
  ws?.close();
  ws = null;
}

export function subscribeWs(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getWsState() {
  return state;
}
