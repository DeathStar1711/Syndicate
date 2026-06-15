import { useApi } from '../hooks/useApi';
import { api } from '../services/api';
import { useState, useEffect, useRef } from 'react';
import { CheckCircle, XCircle, RefreshCw, Play, Brain, AlertTriangle } from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';

interface TrainingStep {
  step: string;
  status: 'start' | 'done' | 'error';
  content: string;
  timestamp: number;
}

export function Settings() {
  const { data: health, refetch } = useApi(() => api.getHealth(), []);
  const { data: mlStatus, refetch: refetchML } = useApi(() => api.getMLStatus(), []);
  const [running, setRunning] = useState<string | null>(null);
  const [trainingSteps, setTrainingSteps] = useState<TrainingStep[]>([]);
  const { lastMessage } = useWebSocket();
  const logRef = useRef<HTMLDivElement>(null);

  // Listen for ML Training pipeline_step events via WebSocket
  useEffect(() => {
    if (!lastMessage) return;
    const msg = lastMessage as { type: string; data: any };
    if (msg.type === 'pipeline_step' && msg.data?.step?.startsWith('ML Training')) {
      const step: TrainingStep = {
        step: msg.data.step,
        status: msg.data.status,
        content: msg.data.content || '',
        timestamp: Date.now(),
      };
      setTrainingSteps(prev => [...prev, step]);

      // Auto-refresh ML status when training completes
      if (msg.data.step === 'ML Training: Complete' || msg.data.status === 'error') {
        setTimeout(() => {
          setRunning(null);
          refetchML();
        }, 1500);
      }
    }
  }, [lastMessage, refetchML]);

  // Auto-scroll training log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [trainingSteps]);

  const runTask = async (task: string) => {
    setRunning(task);
    if (task === 'retrain') {
      setTrainingSteps([]);
    }
    try {
      await api.runTask(task);
      if (task !== 'retrain') {
        setTimeout(() => { setRunning(null); refetch(); }, 2000);
      }
    } catch { setRunning(null); }
  };

  const modelExists = mlStatus?.model_exists;
  const meta = mlStatus?.metadata || {};

  // Get top 5 feature importances
  const featureImportance = meta.feature_importance
    ? Object.entries(meta.feature_importance as Record<string, number>)
        .sort(([, a], [, b]) => (b as number) - (a as number))
        .slice(0, 5)
    : [];
  const maxImportance = featureImportance.length > 0 ? (featureImportance[0][1] as number) : 1;

  const formatModelType = (type: string) => {
    if (!type) return 'Random Forest';
    if (type === 'xgboost') return 'XGBoost';
    return type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  };

  const formatFeatureName = (name: string) => {
    return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
               .replace('Vix', 'VIX').replace('Ema', 'EMA').replace('Macd', 'MACD')
               .replace('Rsi', 'RSI').replace('Atr', 'ATR').replace('Vwap', 'VWAP');
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Settings</h1>
        <p className="page-subtitle">System status and controls</p>
      </div>

      <div className="stats-grid status-grid-3" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <StatusCard
          label="LLM (Ollama)"
          status={health?.llm?.healthy}
          detail={health?.llm?.model || 'gemma4:e4b'}
        />
        <StatusCard
          label="Market"
          status={health?.market_open}
          detail={health?.market_open ? 'Open' : 'Closed'}
        />
        <StatusCard
          label="API Server"
          status={!!health}
          detail={health?.timestamp ? new Date(health.timestamp).toLocaleTimeString('en-IN') : ''}
        />
      </div>

      {/* ML Model Status Card */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Brain size={18} style={{ color: modelExists ? 'var(--profit)' : 'var(--text-muted)' }} />
          <span className="card-title">ML Model Status</span>
          <span style={{
            marginLeft: 'auto',
            fontSize: 11,
            fontWeight: 600,
            padding: '2px 10px',
            borderRadius: 'var(--radius-sm)',
            background: modelExists ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            color: modelExists ? 'var(--profit)' : 'var(--loss)',
          }}>
            {modelExists ? 'Trained' : 'Not Trained'}
          </span>
        </div>

        {modelExists ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {/* Metrics */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <MetricRow label="Model Type" value={formatModelType(meta.model_type)} />
              <MetricRow label="Trained On" value={meta.training_date ? new Date(meta.training_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : 'N/A'} />
              <MetricRow label="Samples" value={meta.samples?.toLocaleString() || 'N/A'} />
              <MetricRow label="Precision" value={meta.test_precision ? `${(meta.test_precision * 100).toFixed(1)}%` : 'N/A'} highlight={meta.test_precision >= 0.6} />
              <MetricRow label="Recall" value={meta.test_recall ? `${(meta.test_recall * 100).toFixed(1)}%` : 'N/A'} />
              <MetricRow label="Threshold" value={meta.threshold?.toFixed(4) || 'N/A'} />
              <MetricRow label="CV Precision" value={meta.cv_mean ? `${(meta.cv_mean * 100).toFixed(1)}% ± ${(meta.cv_std * 100).toFixed(1)}%` : 'N/A'} />
            </div>

            {/* Feature Importance */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>Top Features</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {featureImportance.map(([name, value]) => (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', width: 110, textAlign: 'right', flexShrink: 0 }}>
                      {formatFeatureName(name)}
                    </div>
                    <div style={{ flex: 1, height: 6, background: 'var(--bg-glass)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{
                        width: `${((value as number) / maxImportance) * 100}%`,
                        height: '100%',
                        background: 'linear-gradient(90deg, var(--accent), var(--profit))',
                        borderRadius: 3,
                        transition: 'width 0.4s ease',
                      }} />
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', width: 36, textAlign: 'right' }}>
                      {((value as number) * 100).toFixed(1)}%
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div style={{ padding: '20px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            <AlertTriangle size={28} style={{ margin: '0 auto 8px', display: 'block', opacity: 0.5 }} />
            No trained model found. Click "Retrain Model" below to train one.
          </div>
        )}

        {/* Live Training Log */}
        {trainingSteps.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>Training Log</div>
            <div
              ref={logRef}
              style={{
                maxHeight: 200,
                overflowY: 'auto',
                background: 'var(--bg-primary)',
                borderRadius: 'var(--radius-sm)',
                padding: '8px 12px',
                fontSize: 12,
                fontFamily: 'monospace',
                lineHeight: 1.6,
              }}
            >
              {trainingSteps.map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, color: s.status === 'error' ? 'var(--loss)' : s.status === 'done' ? 'var(--profit)' : 'var(--text-secondary)' }}>
                  {s.status === 'start' && <RefreshCw size={11} className="spinning" />}
                  {s.status === 'done' && <CheckCircle size={11} />}
                  {s.status === 'error' && <XCircle size={11} />}
                  <span style={{ color: 'var(--text-muted)' }}>{new Date(s.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                  <span>{s.step.replace('ML Training: ', '')}</span>
                  {s.content && <span style={{ color: 'var(--text-muted)' }}>— {s.content}</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Manual Task Triggers */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header"><span className="card-title">Manual Actions</span></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <TaskButton label="Generate Signals" task="generate_signals" desc="Run the signal generation pipeline now"
            running={running} onRun={runTask} />
          <TaskButton label="Market Briefing" task="market_briefing" desc="Generate a fresh LLM market briefing"
            running={running} onRun={runTask} />
          <TaskButton label="Check Exits" task="check_exits" desc="Check open positions for SL/target hits"
            running={running} onRun={runTask} />
          <TaskButton label="Retrain Model" task="retrain" desc="Download data & train the ML confidence model"
            running={running} onRun={runTask} icon={<Brain size={14} />} />
        </div>
      </div>

      {/* System Info */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header"><span className="card-title">System Info</span></div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 2 }}>
          <div><strong>LLM Model:</strong> {health?.llm?.model || 'N/A'}</div>
          <div><strong>LLM Cache:</strong> {health?.llm?.cache_size || 0} entries</div>
          <div><strong>ML Model:</strong> {modelExists ? `${formatModelType(meta.model_type)} (precision: ${((meta.test_precision || 0) * 100).toFixed(1)}%)` : 'Not trained'}</div>
          <div><strong>Mode:</strong> Paper Trading</div>
          <div><strong>API:</strong> http://localhost:8000</div>
          <div><strong>Dashboard:</strong> http://localhost:5173</div>
        </div>
      </div>
    </div>
  );
}

function StatusCard({ label, status, detail }: { label: string; status?: boolean; detail: string }) {
  return (
    <div className="stat-card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      {status ? <CheckCircle size={24} color="var(--profit)" /> : <XCircle size={24} color="var(--loss)" />}
      <div>
        <div className="stat-label">{label}</div>
        <div style={{ fontSize: 14, fontWeight: 600, color: status ? 'var(--profit)' : 'var(--loss)', marginTop: 2 }}>
          {status ? 'Connected' : 'Disconnected'}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{detail}</div>
      </div>
    </div>
  );
}

function MetricRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: highlight ? 'var(--profit)' : 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

function TaskButton({ label, task, desc, running, onRun, icon }: {
  label: string; task: string; desc: string; running: string | null; onRun: (t: string) => void; icon?: React.ReactNode;
}) {
  const isRunning = running === task;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'var(--bg-glass)', borderRadius: 'var(--radius-sm)' }}>
      <div>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{desc}</div>
      </div>
      <button className="btn btn-ghost btn-sm" onClick={() => onRun(task)} disabled={isRunning}>
        {isRunning ? <RefreshCw size={14} className="spinning" /> : (icon || <Play size={14} />)}
        {isRunning ? 'Running...' : 'Run'}
      </button>
    </div>
  );
}
