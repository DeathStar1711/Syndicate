import { useCachedApi, readCache } from '../stores/dataCache';
import { api } from '../services/api';
import { TrendingUp, TrendingDown, IndianRupee, Target, Trophy, AlertTriangle, RefreshCw } from 'lucide-react';

export function Dashboard() {
  const { data: portfolio, loading: portfolioLoading, refreshing: portfolioRefreshing } = useCachedApi(
    'portfolio',
    () => api.getPortfolio(),
    30_000,
  );

  const { data: signals } = useCachedApi(
    'signals',
    () => api.getSignals(),
    30_000,
  );

  const { data: briefingData, loading: briefingLoading, refreshing: briefingRefreshing } = useCachedApi(
    'briefing',
    () => api.getMarketBriefing(),
    3_600_000, // 1 hour stale
  );

  const { data: sectorsData, loading: sectorsLoading } = useCachedApi(
    'sectors',
    () => api.getSectors(),
    300_000, // 5 min stale
  );

  if (portfolioLoading) {
    return (
      <div>
        <div className="page-header">
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">AI-powered trading overview</p>
        </div>
        <div className="loading-spinner" style={{ marginTop: 40 }} />
      </div>
    );
  }

  const summary = portfolio?.summary;

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">AI-powered trading overview</p>
        </div>
        {(portfolioRefreshing || briefingRefreshing) && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <RefreshCw size={12} className="spinning" /> Updating...
          </span>
        )}
      </div>

      {/* Stats Grid */}
      <div className="stats-grid">
        <StatCard label="Total Invested" value={`₹${(summary?.invested_capital || 0).toLocaleString('en-IN')}`}
          icon={<IndianRupee size={18} />} />
        <StatCard label="Total P&L" value={`₹${(summary?.total_pnl || 0).toLocaleString('en-IN')}`}
          positive={(summary?.total_pnl || 0) >= 0} icon={(summary?.total_pnl || 0) >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />} />
        <StatCard label="Win Rate" value={`${summary?.win_rate || 0}%`}
          change={`${summary?.wins || 0}W / ${summary?.losses || 0}L`} icon={<Trophy size={18} />} />
        <StatCard label="Active Positions" value={`${summary?.open_positions || 0}`}
          icon={<Target size={18} />} />
      </div>

      <div className="two-col">
        {/* Market Briefing */}
        <div className="briefing-card">
          <div className="card-header">
            <span className="card-title">🤖 AI Market Briefing</span>
            {briefingData?.briefing && <span className={`badge badge-${briefingData.briefing.market_mood?.includes('bullish') ? 'bullish' : briefingData.briefing.market_mood?.includes('bearish') ? 'bearish' : 'neutral'}`}>{briefingData.briefing.market_mood || 'N/A'}</span>}
          </div>
          {briefingLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '20px 0' }}>
              <div className="loading-spinner" style={{ width: 24, height: 24, borderWidth: 2 }} />
            </div>
          ) : briefingData?.briefing ? (
            <>
              <p style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--text-secondary)', marginBottom: 16 }}>
                {briefingData.briefing.summary}
              </p>
              {briefingData.briefing.trading_advice && (
                <div className="signal-reasoning">
                  <strong style={{ color: 'var(--accent-cyan)' }}>Trading Advice:</strong><br />
                  {briefingData.briefing.trading_advice}
                </div>
              )}
              {briefingData.briefing.risk_factors?.length > 0 && (
                <div style={{ marginTop: 12, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {briefingData.briefing.risk_factors.map((r: string, i: number) => (
                    <span key={i} style={{ fontSize: 11, padding: '3px 8px', borderRadius: 12, background: 'var(--loss-bg)', color: 'var(--loss)' }}>
                      <AlertTriangle size={10} style={{ marginRight: 3 }} />{r}
                    </span>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
              Market briefing will appear here before market opens (8:45 AM IST)
            </p>
          )}
        </div>

        {/* Sector Heatmap */}
        <div className="card">
          <div className="card-header"><span className="card-title">Sector Performance</span></div>
          {sectorsLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '20px 0' }}>
              <div className="loading-spinner" style={{ width: 24, height: 24, borderWidth: 2 }} />
            </div>
          ) : (
            <div className="sector-grid">
              {sectorsData?.sectors && Object.entries(sectorsData.sectors).map(([name, data]: [string, any]) => {
                const pct = data?.change_pct || 0;
                const isUp = pct >= 0;
                return (
                  <div key={name} className="sector-cell" style={{
                    background: isUp ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                    color: isUp ? 'var(--profit)' : 'var(--loss)',
                  }}>
                    <div className="sector-name" style={{ color: 'var(--text-secondary)' }}>{name}</div>
                    <div className="sector-change">{isUp ? '+' : ''}{pct.toFixed(1)}%</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Top Signals Preview */}
      {signals?.data?.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div className="card-header"><span className="card-title">⚡ Today's Top Picks</span></div>
          <div style={{ display: 'flex', gap: 16, overflowX: 'auto', paddingBottom: 8 }}>
            {signals.data.slice(0, 3).map((sig: any) => (
              <div key={sig.ticker} className="signal-card" style={{ minWidth: 280, flex: '0 0 auto' }}>
                <div className="signal-header">
                  <span className="signal-ticker">{sig.ticker.replace('.NS', '')}</span>
                  {sig.llm_verdict && <span className={`badge badge-${sig.llm_verdict.replace('_', '-')}`}>{sig.llm_verdict.replace('_', ' ')}</span>}
                </div>
                <div className="confidence-bar">
                  <div className="confidence-fill" style={{
                    width: `${sig.llm_confidence || sig.confidence}%`,
                    background: (sig.llm_confidence || sig.confidence) > 70 ? 'var(--profit)' : (sig.llm_confidence || sig.confidence) > 50 ? 'var(--hold)' : 'var(--loss)',
                  }} />
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Confidence: {sig.llm_confidence || sig.confidence}%</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, change, positive, icon }: {
  label: string; value: string; change?: string; positive?: boolean; icon: React.ReactNode;
}) {
  return (
    <div className="stat-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="stat-label">{label}</span>
        <span style={{ color: 'var(--text-muted)' }}>{icon}</span>
      </div>
      <div className="stat-value">{value}</div>
      {change && <div className={`stat-change ${positive === true ? 'positive' : positive === false ? 'negative' : ''}`}>{change}</div>}
    </div>
  );
}
