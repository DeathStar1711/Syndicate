const API_BASE = import.meta.env.VITE_API_URL || '';

export const api = {
  // ── Signals ───────────────────────────────────────
  async getSignals() {
    const res = await fetch(`${API_BASE}/api/signals`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async generateSignals() {
    const res = await fetch(`${API_BASE}/api/signals/generate`, { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  // ── Portfolio ─────────────────────────────────────
  async getPortfolio() {
    const res = await fetch(`${API_BASE}/api/portfolio`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async getTradeHistory(limit = 50) {
    const res = await fetch(`${API_BASE}/api/portfolio/history?limit=${limit}`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async addToPortfolio(signal: {
    ticker: string; direction: string; stop_loss: number; target: number;
    confidence: number; risk_reward: number; reasons: string[];
    cons: string[]; llm_verdict?: string; llm_reasoning?: string;
    shares?: number;
  }) {
    const res = await fetch(`${API_BASE}/api/portfolio/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(signal),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to add trade');
    }
    return res.json();
  },

  async closeTrade(tradeId: number, reason = 'manual') {
    const res = await fetch(`${API_BASE}/api/portfolio/close/${tradeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exit_reason: reason }),
    });
    if (!res.ok) {
      let detail = `Trade close failed (${res.status})`;
      try {
        const err = await res.json();
        detail = err.detail || detail;
      } catch { /* response wasn't JSON */ }
      throw new Error(detail);
    }
    return res.json();
  },

  // ── Market ────────────────────────────────────────
  async getMarketBriefing() {
    const res = await fetch(`${API_BASE}/api/market/briefing`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async getMarketStatus() {
    const res = await fetch(`${API_BASE}/api/market/status`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async getSectors() {
    const res = await fetch(`${API_BASE}/api/market/sectors`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async getHistoricalData(ticker: string, period: string = "3mo") {
    const res = await fetch(`${API_BASE}/api/market/history/${ticker}?period=${period}`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  // ── System ────────────────────────────────────────
  async getHealth() {
    const res = await fetch(`${API_BASE}/api/system/health`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async runTask(task: string) {
    const res = await fetch(`${API_BASE}/api/system/run/${task}`, { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async getMLStatus() {
    const res = await fetch(`${API_BASE}/api/system/ml-status`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  async getMistakes() {
    const res = await fetch(`${API_BASE}/api/trades/mistakes`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  },

  // ── WebSocket URL ─────────────────────────────────
  getWsUrl: () => {
    if (API_BASE) return `${API_BASE.replace('http', 'ws')}/ws`;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws`;
  },
};
