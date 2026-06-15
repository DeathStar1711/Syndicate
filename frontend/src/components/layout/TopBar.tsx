import { useApi } from '../../hooks/useApi';
import { api } from '../../services/api';

type MarketStatus = {
  is_open: boolean;
  current_time: string;
  nifty?: { value: number; change: number; change_pct: number };
  sensex?: { value: number; change: number; change_pct: number };
};

export function TopBar({ wsConnected }: { wsConnected: boolean }) {
  const { data } = useApi<MarketStatus>(() => api.getMarketStatus(), []);

  return (
    <div className="top-bar" style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '12px 0', marginBottom: 8, borderBottom: '1px solid var(--border)',
      flexWrap: 'wrap', gap: 8,
    }}>
      <div className="top-bar-indices" style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
        {data?.nifty && (
          <IndexChip label="NIFTY 50" value={data.nifty.value} change={data.nifty.change_pct} />
        )}
        {data?.sensex && (
          <IndexChip label="SENSEX" value={data.sensex.value} change={data.sensex.change_pct} />
        )}
      </div>
      <div className="top-bar-status" style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 13 }}>
        <span className="live-dot" style={{ background: wsConnected ? 'var(--accent-emerald)' : 'var(--loss)' }} />
        <span style={{ color: 'var(--text-muted)' }}>
          {data?.is_open ? '🟢 Market Open' : '🔴 Market Closed'} · {data?.current_time || '--'}
        </span>
      </div>
    </div>
  );
}

function IndexChip({ label, value, change }: { label: string; value: number; change: number }) {
  const safeChange = change || 0;
  const isUp = safeChange >= 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 15 }}>
        {(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
      </span>
      <span style={{
        fontSize: 12, fontWeight: 600, fontFamily: 'var(--font-mono)',
        color: isUp ? 'var(--profit)' : 'var(--loss)',
      }}>
        {isUp ? '▲' : '▼'} {Math.abs(safeChange).toFixed(2)}%
      </span>
    </div>
  );
}
