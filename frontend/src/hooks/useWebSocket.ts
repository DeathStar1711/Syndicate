import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '../services/api';

type WsMessage = {
  type: string;
  data: unknown;
};

export function useWebSocket(onMessage?: (msg: WsMessage) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const reconnectTimer = useRef<number | undefined>(undefined);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(api.getWsUrl());

      ws.onopen = () => {
        setConnected(true);
        // Heartbeat
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
        ws.addEventListener('close', () => clearInterval(ping));
      };

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data);
          setLastMessage(msg);
          if (onMessage) onMessage(msg);

          if (msg.type === 'price_update' && typeof msg.data === 'object') {
            setPrices(prev => ({ ...prev, ...(msg.data as Record<string, number>) }));
          }
        } catch { /* ignore malformed */ }
      };

      ws.onclose = () => {
        setConnected(false);
        // Auto-reconnect after 3s
        reconnectTimer.current = window.setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();
      wsRef.current = ws;
    } catch { setConnected(false); }
  }, [onMessage]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, lastMessage, prices };
}
