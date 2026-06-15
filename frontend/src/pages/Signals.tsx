import { useState, useMemo, useEffect, useRef, useCallback, useSyncExternalStore } from 'react';
import { useCachedApi, invalidateCache } from '../stores/dataCache';
import {
  subscribe as pipelineSubscribe,
  getSteps, isGenerating, isShowLog, getHasRun,
  startGeneration, addPipelineStep, finishGeneration,
  setShowLog as pipelineSetShowLog,
} from '../stores/pipelineStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { api } from '../services/api';
import { RefreshCw, PlusCircle, ChevronDown, ChevronUp, Bot, CheckCircle2, Loader2, AlertTriangle, X } from 'lucide-react';
import { TradingViewChart } from '../components/charts/TradingViewChart';

type PipelineStep = {
  step: string;
  ticker: string;
  status: 'start' | 'done' | 'error';
  content: string;
  timestamp: number;
};

function PipelineLog({ steps, onClose }: { steps: PipelineStep[]; onClose: () => void }) {
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [steps]);

  const getIcon = (status: string) => {
    if (status === 'start') return <Loader2 size={14} className="spinning" style={{ color: 'var(--accent)' }} />;
    if (status === 'done') return <CheckCircle2 size={14} style={{ color: 'var(--profit)' }} />;
    return <AlertTriangle size={14} style={{ color: 'var(--loss)' }} />;
  };

  return (
    <div style={{
      background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 'var(--radius-lg)', marginBottom: 24,
      maxHeight: 400, overflowY: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12,
      position: 'relative',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0, background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)', padding: '12px 16px', zIndex: 10, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Bot size={16} style={{ color: 'var(--accent)' }} />
          <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-primary)', color: 'var(--text-primary)' }}>
            AI Pipeline Log
          </span>
        </div>
        <button onClick={onClose} className="btn btn-ghost btn-sm" style={{ padding: '2px 6px', minWidth: 'auto' }}>
          <X size={14} />
        </button>
      </div>

      <div style={{ padding: '8px 16px 16px 16px' }}>
        {steps.length === 0 && (
          <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 16 }}>
            Waiting for pipeline events...
          </div>
        )}

        {steps.map((s, i) => {
        const tickerLabel = s.ticker ? ` [${s.ticker.replace('.NS', '')}]` : '';
        const timeStr = new Date(s.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        return (
          <div key={i} style={{
            display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 0',
            borderBottom: '1px solid rgba(255,255,255,0.04)',
            opacity: s.status === 'start' ? 0.7 : 1,
          }}>
            <span style={{ flexShrink: 0, marginTop: 4 }}>{getIcon(s.status)}</span>
            <div style={{ flex: 1, lineHeight: 1.5, minWidth: 0 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', alignItems: 'baseline', marginBottom: 4 }}>
                <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: 11 }}>{timeStr}</span>
                <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{s.step}</span>
                {tickerLabel && <span style={{ color: 'rgba(255,255,255,0.6)' }}>{tickerLabel}</span>}
              </div>
              {s.content && s.status !== 'start' && (
                <div style={{ color: 'rgba(255,255,255,0.85)', marginTop: 4, wordBreak: 'break-word', fontSize: 13, lineHeight: 1.6 }}>
                  {s.content}
                </div>
              )}
              {s.content && s.status === 'start' && (
                <div style={{ color: 'rgba(255,255,255,0.5)', marginTop: 2, fontSize: 12 }}>{s.content}</div>
              )}
            </div>
          </div>
        );
      })}
      <div ref={logEndRef} />
      </div>
    </div>
  );
}


function SignalChart({ ticker }: { ticker: string }) {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // useEffect-based because chart data is per-ticker, not a global cache concern
  useEffect(() => {
    api.getHistoricalData(ticker, '3mo').then((res) => {
      if (res.status === 'ok' && res.data) {
        setData(res.data);
      }
      setLoading(false);
    }).catch((err) => {
      console.error("Chart data error:", err);
      setLoading(false);
    });
  }, [ticker]);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 250 }}>
        <div className="loading-spinner" />
      </div>
    );
  }
  
  if (!data.length) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 250, color: 'var(--text-muted)' }}>
        No chart data available.
      </div>
    );
  }

  return <TradingViewChart data={data} height={250} />;
}

export function Signals() {
  const { data, loading } = useCachedApi('signals', () => api.getSignals(), 30_000);
  const { data: portfolioData } = useCachedApi('portfolio', () => api.getPortfolio(), 30_000);
  const [adding, setAdding] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [shareQty, setShareQty] = useState<Record<string, number>>({});

  // Read pipeline state from the persistent singleton store
  const pipelineSteps = useSyncExternalStore(pipelineSubscribe, getSteps);
  const generating = useSyncExternalStore(pipelineSubscribe, isGenerating);
  const showLog = useSyncExternalStore(pipelineSubscribe, isShowLog);
  const hasRun = useSyncExternalStore(pipelineSubscribe, getHasRun);

  // Handle WebSocket events — always process pipeline steps regardless of
  // which page the user is viewing (the store is global).
  useWebSocket(useCallback((msg: any) => {
    if (msg.type === 'pipeline_step') {
      const step = msg.data;
      addPipelineStep(step);

      // Auto-show log when first pipeline step arrives
      pipelineSetShowLog(true);

      // If pipeline is complete or errored, stop generating
      if (step.step === 'Pipeline Complete' || step.step === 'Pipeline Error') {
        finishGeneration();
        invalidateCache('signals');
      }
    }

    if (msg.type === 'signals_updated') {
      finishGeneration();
      invalidateCache('signals');
    }
  }, []));

  // Tickers already in portfolio
  const portfolioTickers = useMemo(() => {
    const positions = portfolioData?.open_positions || [];
    return new Set(positions.map((p: any) => p.ticker));
  }, [portfolioData]);

  const handleGenerate = async () => {
    startGeneration();
    await api.generateSignals();

    // Fallback timeout — if no WS events arrive, stop after 3 minutes
    setTimeout(() => {
      if (isGenerating()) {
        finishGeneration();
        invalidateCache('signals');
      }
    }, 180_000);
  };

  const handleAdd = async (signal: any) => {
    const shares = shareQty[signal.ticker] || 1;
    setAdding(signal.ticker);
    try {
      await api.addToPortfolio({
        ticker: signal.ticker,
        direction: signal.direction || 'long',
        stop_loss: signal.stop_loss,
        target: signal.target,
        confidence: signal.llm_confidence || signal.confidence,
        risk_reward: signal.risk_reward,
        reasons: signal.reasons || [],
        cons: signal.cons || [],
        llm_verdict: signal.llm_verdict,
        llm_reasoning: signal.llm_reasoning,
        shares,
      });
      alert(`✅ ${signal.ticker} added to portfolio (${shares} shares) at current market price!`);
      // Refresh both caches
      invalidateCache('portfolio');
      invalidateCache('signals');
    } catch (e: any) {
      alert(`❌ ${e.message}`);
    } finally {
      setAdding(null);
    }
  };

  // Filter out stocks already in portfolio
  const allSignals = data?.data || [];
  const signals = allSignals.filter((sig: any) => !portfolioTickers.has(sig.ticker));

  // Determine if signals were ever generated (either from cache or this session)
  const signalsGenerated = data?.timestamp || hasRun;

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 className="page-title">Trade Signals</h1>
          <p className="page-subtitle">
            {data?.timestamp ? `Generated: ${new Date(data.timestamp).toLocaleTimeString('en-IN')}` : 'No signals yet'}
            {' · '}{signals.length} picks
            {allSignals.length !== signals.length && ` (${allSignals.length - signals.length} in portfolio)`}
          </p>
        </div>
        <button className="btn btn-primary" onClick={handleGenerate} disabled={generating}>
          <RefreshCw size={14} className={generating ? 'spinning' : ''} />
          {generating ? 'Generating...' : 'Generate Signals'}
        </button>
      </div>

      {/* Live Pipeline Log */}
      {showLog && (generating || pipelineSteps.length > 0) && (
        <PipelineLog
          steps={pipelineSteps}
          onClose={() => pipelineSetShowLog(false)}
        />
      )}

      {loading ? (
        <div className="loading-spinner" />
      ) : signals.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">{generating ? '🔄' : signalsGenerated ? '📭' : '⚡'}</div>
          <p>
            {generating
              ? 'AI pipeline is running. Watch the live log above...'
              : allSignals.length === 0
                ? signalsGenerated
                  ? 'No trade setups found for today.\nThe strategy engine found no stocks meeting the entry criteria.'
                  : 'No signals generated yet.\nClick "Generate Signals" to run the AI pipeline.'
                : 'All signals are already in your portfolio!'}
          </p>
        </div>
      ) : (
        <div className="signals-grid">
          {signals.map((sig: any) => {
            const confidence = sig.llm_confidence || sig.confidence || 0;
            const isExpanded = expanded === sig.ticker;
            const qty = shareQty[sig.ticker] || 1;

            return (
              <div key={sig.ticker} className="signal-card">
                {/* Header */}
                <div className="signal-header">
                  <div>
                    <span className="signal-ticker">{sig.ticker.replace('.NS', '')}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>{sig.direction?.toUpperCase() || 'LONG'}</span>
                  </div>
                  {sig.llm_verdict && (
                    <span className={`badge badge-${sig.llm_verdict.replace('_', '-')}`}>
                      {sig.llm_verdict.replace('_', ' ')}
                    </span>
                  )}
                </div>

                {/* Confidence Bar */}
                <div className="confidence-bar">
                  <div className="confidence-fill" style={{
                    width: `${confidence}%`,
                    background: confidence > 70 ? 'var(--profit)' : confidence > 50 ? 'var(--hold)' : 'var(--loss)',
                  }} />
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                  Confidence: {confidence}% · R:R {sig.risk_reward?.toFixed(1) || 'N/A'}:1
                </div>

                {/* Prices */}
                <div className="signal-prices">
                  <div className="signal-price-item">
                    <div className="signal-price-label">Entry</div>
                    <div className="signal-price-value">₹{sig.entry_price?.toFixed(2)}</div>
                  </div>
                  <div className="signal-price-item" style={{ borderLeft: '2px solid var(--loss)', background: 'var(--loss-bg)' }}>
                    <div className="signal-price-label">Stop Loss</div>
                    <div className="signal-price-value" style={{ color: 'var(--loss)' }}>₹{sig.stop_loss?.toFixed(2)}</div>
                  </div>
                  <div className="signal-price-item" style={{ borderLeft: '2px solid var(--profit)', background: 'var(--profit-bg)' }}>
                    <div className="signal-price-label">Target</div>
                    <div className="signal-price-value" style={{ color: 'var(--profit)' }}>₹{sig.target?.toFixed(2)}</div>
                  </div>
                </div>

                {/* LLM Reasoning */}
                {sig.llm_reasoning && sig.llm_reasoning !== 'LLM analysis unavailable' && (
                  <div className="signal-reasoning">
                    <strong>🤖 AI Analysis:</strong> {sig.llm_reasoning}
                  </div>
                )}

                {/* Expandable Details */}
                <button className="btn btn-ghost btn-sm btn-full" onClick={() => setExpanded(isExpanded ? null : sig.ticker)}
                  style={{ marginTop: 8 }}>
                  {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  {isExpanded ? 'Less' : 'Details'}
                </button>

                {isExpanded && (
                  <div style={{ marginTop: 12, fontSize: 13, color: 'var(--text-secondary)' }}>
                    {sig.reasons?.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        <strong style={{ color: 'var(--profit)' }}>Pros:</strong>
                        <ul style={{ paddingLeft: 16, margin: '4px 0' }}>
                          {sig.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}
                        </ul>
                      </div>
                    )}
                    {sig.cons?.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        <strong style={{ color: 'var(--loss)' }}>Cons:</strong>
                        <ul style={{ paddingLeft: 16, margin: '4px 0' }}>
                          {sig.cons.map((c: string, i: number) => <li key={i}>{c}</li>)}
                        </ul>
                      </div>
                    )}
                    {sig.llm_key_risk && (
                      <div style={{ marginTop: 8, marginBottom: 12, padding: 8, background: 'var(--loss-bg)', borderRadius: 'var(--radius-sm)', fontSize: 12 }}>
                        ⚠️ <strong>Key Risk:</strong> {sig.llm_key_risk}
                      </div>
                    )}
                    {sig.news_fallback && (
                      <div style={{ marginTop: 8, marginBottom: 12, padding: 8, background: 'var(--accent-amber-dim)', color: 'var(--accent-amber)', borderRadius: 'var(--radius-sm)', fontSize: 12 }}>
                        ⚠️ <strong>Search Fallback:</strong> Live web search blocked. Used Google News RSS fallback.
                      </div>
                    )}
                    
                    {/* TradingView Chart */}
                    <div style={{ marginTop: 16, marginBottom: 16, borderRadius: 'var(--radius-md)', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.05)' }}>
                      <SignalChart ticker={sig.ticker} />
                    </div>
                  </div>
                )}

                {/* Share Quantity + Add to Portfolio */}
                <div className="signal-actions" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 0,
                    border: '1px solid rgba(255,255,255,0.1)', borderRadius: 'var(--radius-sm)',
                    overflow: 'hidden', flexShrink: 0,
                  }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ borderRadius: 0, padding: '6px 10px', minWidth: 32 }}
                      onClick={() => setShareQty(prev => ({ ...prev, [sig.ticker]: Math.max(1, (prev[sig.ticker] || 1) - 1) }))}
                    >−</button>
                    <input
                      type="number"
                      min={1}
                      value={qty}
                      onChange={(e) => {
                        const v = parseInt(e.target.value) || 1;
                        setShareQty(prev => ({ ...prev, [sig.ticker]: Math.max(1, v) }));
                      }}
                      style={{
                        width: 48, textAlign: 'center', border: 'none',
                        background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)',
                        fontFamily: 'var(--font-mono)', fontSize: 13, padding: '6px 0',
                        outline: 'none',
                      }}
                    />
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ borderRadius: 0, padding: '6px 10px', minWidth: 32 }}
                      onClick={() => setShareQty(prev => ({ ...prev, [sig.ticker]: (prev[sig.ticker] || 1) + 1 }))}
                    >+</button>
                  </div>
                  <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => handleAdd(sig)}
                    disabled={adding === sig.ticker}>
                    <PlusCircle size={14} />
                    {adding === sig.ticker ? 'Adding...' : `Add ${qty} share${qty > 1 ? 's' : ''}`}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
