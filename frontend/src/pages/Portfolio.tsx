import { useCachedApi, invalidateCache } from '../stores/dataCache';
import { useWebSocket } from '../hooks/useWebSocket';
import { api } from '../services/api';
import { useState } from 'react';
import { XCircle, TrendingUp, TrendingDown } from 'lucide-react';

function ConfirmModal({ ticker, onConfirm, onCancel, loading }: {
  ticker: string; onConfirm: () => void; onCancel: () => void; loading: boolean;
}) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
    }} onClick={onCancel}>
      <div style={{
        background: 'var(--bg-card)', borderRadius: 'var(--radius-lg)',
        padding: 24, minWidth: 320, maxWidth: 400,
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
      }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 700 }}>Close Trade</h3>
        <p style={{ fontSize: 14, color: 'var(--text-secondary)', margin: '0 0 20px' }}>
          Close <strong style={{ color: 'var(--text-primary)' }}>{ticker.replace('.NS', '')}</strong> at current market price?
        </p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onCancel} disabled={loading}>Cancel</button>
          <button className="btn btn-danger" onClick={onConfirm} disabled={loading}>
            {loading ? 'Closing...' : 'Close Trade'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Portfolio() {
  const { data, loading, refreshing } = useCachedApi('portfolio', () => api.getPortfolio(), 30_000);
  const { data: history } = useCachedApi('trade_history', () => api.getTradeHistory(30), 60_000);
  const { prices } = useWebSocket();
  const [confirmCloseId, setConfirmCloseId] = useState<number | null>(null);
  const [closingId, setClosingId] = useState<number | null>(null);

  const summary = data?.summary;
  const positions = data?.open_positions || [];

  const handleClose = async (tradeId: number) => {
    setClosingId(tradeId);
    try {
      await api.closeTrade(tradeId);
      setConfirmCloseId(null);
      invalidateCache('portfolio');
      invalidateCache('trade_history');
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    } finally {
      setClosingId(null);
    }
  };

  const closingTrade = positions.find((p: any) => p.id === confirmCloseId);

  return (
    <div>
      {/* Close Trade Modal */}
      {confirmCloseId !== null && closingTrade && (
        <ConfirmModal
          ticker={closingTrade.ticker}
          onConfirm={() => handleClose(confirmCloseId)}
          onCancel={() => setConfirmCloseId(null)}
          loading={closingId === confirmCloseId}
        />
      )}

      <div className="page-header">
        <h1 className="page-title">Portfolio</h1>
        <p className="page-subtitle">{positions.length} active position{positions.length !== 1 ? 's' : ''}</p>
      </div>

      {/* Summary Stats */}
      {summary && (
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-label">Total Invested</span>
            <div className="stat-value">₹{summary.invested_capital?.toLocaleString('en-IN')}</div>
          </div>
          <div className="stat-card">
            <span className="stat-label">Total Profit</span>
            <div className="stat-value" style={{ color: 'var(--profit)' }}>
              ₹{summary.total_profit_amount?.toLocaleString('en-IN')}
            </div>
          </div>
          <div className="stat-card">
            <span className="stat-label">Total Loss</span>
            <div className="stat-value" style={{ color: 'var(--loss)' }}>
              ₹{Math.abs(summary.total_loss_amount || 0)?.toLocaleString('en-IN')}
            </div>
          </div>
          <div className="stat-card">
            <span className="stat-label">P/L Ratio</span>
            <div className="stat-value">
              {summary.pl_ratio?.toFixed(2)}
            </div>
          </div>
        </div>
      )}

      {/* Open Positions */}
      {loading ? <div className="loading-spinner" /> : positions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📊</div>
          <p>No active positions.<br />Add trades from the Signals page.</p>
        </div>
      ) : (
        <div style={{ marginBottom: 32 }}>
          <div className="card-header"><span className="card-title">Active Positions</span></div>
          <div className="signals-grid">
            {positions.map((pos: any) => {
              const livePrice = prices[pos.ticker] || pos.current_price || pos.entry_price;
              const entry = pos.entry_price;
              const pnl = pos.direction === 'long'
                ? (livePrice - entry) * pos.shares
                : (entry - livePrice) * pos.shares;
              const pnlPct = (pnl / (entry * pos.shares)) * 100;

              const sl = pos.stop_loss;
              const tgt = pos.target;
              const range = tgt - sl;
              const progress = range > 0 ? Math.max(0, Math.min(100, ((livePrice - sl) / range) * 100)) : 50;

              return (
                <div key={pos.id} className="signal-card">
                  <div className="signal-header">
                    <div>
                      <span className="signal-ticker">{pos.ticker.replace('.NS', '')}</span>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>#{pos.id}</span>
                    </div>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span className="live-dot" />
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700 }}>
                        ₹{livePrice?.toFixed(2)}
                      </span>
                    </span>
                  </div>

                  {/* P&L */}
                  <div style={{
                    padding: '12px 16px', borderRadius: 'var(--radius-sm)', margin: '8px 0',
                    background: pnl >= 0 ? 'var(--profit-bg)' : 'var(--loss-bg)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  }}>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Unrealized P&L</div>
                      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-mono)', color: pnl >= 0 ? 'var(--profit)' : 'var(--loss)' }}>
                        {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                      </div>
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: pnl >= 0 ? 'var(--profit)' : 'var(--loss)' }}>
                      {pnl >= 0 ? <TrendingUp size={20} /> : <TrendingDown size={20} />}
                      {' '}{pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                    </div>
                  </div>

                  {/* Price Progress */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                    <span>SL: ₹{sl?.toFixed(2)}</span>
                    <span>Entry: ₹{entry?.toFixed(2)}</span>
                    <span>Target: ₹{tgt?.toFixed(2)}</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${progress}%` }} />
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                    <span>{pos.shares} shares · ₹{pos.position_value?.toLocaleString('en-IN')}</span>
                  </div>

                  <button className="btn btn-danger btn-sm btn-full" style={{ marginTop: 12 }}
                    onClick={() => setConfirmCloseId(pos.id)} disabled={closingId === pos.id}>
                    <XCircle size={14} />
                    {closingId === pos.id ? 'Closing...' : 'Close Trade'}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Trade History */}
      {history?.trades?.length > 0 && (
        <div className="card" style={{ marginTop: 24 }}>
          <div className="card-header"><span className="card-title">Trade History</span></div>
          <div style={{ overflowX: 'auto' }}>
            <table className="trade-table">
              <thead>
                <tr>
                  <th>Ticker</th><th>Entry</th><th>Exit</th><th>P&L</th><th>%</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {history.trades.map((t: any) => (
                  <tr key={t.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{t.ticker?.replace('.NS', '')}</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>₹{t.entry_price?.toFixed(2)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>₹{t.exit_price?.toFixed(2)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: (t.pnl || 0) >= 0 ? 'var(--profit)' : 'var(--loss)' }}>
                      {t.pnl >= 0 ? '+' : ''}₹{t.pnl?.toFixed(2)}
                    </td>
                    <td style={{ color: (t.pnl_pct || 0) >= 0 ? 'var(--profit)' : 'var(--loss)' }}>
                      {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct?.toFixed(1)}%
                    </td>
                    <td><span className="badge badge-neutral">{t.exit_reason}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
