/**
 * Persistent pipeline log store — lives outside React tree so it
 * survives route changes (tab switches).
 *
 * Uses the same subscribe/notify pattern as dataCache.ts.
 */

export type PipelineStep = {
  step: string;
  ticker: string;
  status: 'start' | 'done' | 'error';
  content: string;
  timestamp: number;
};

type Listener = () => void;

// ── Singleton state ──────────────────────────────────
let steps: PipelineStep[] = [];
let generating = false;
let showLog = false;
let hasRun = false;
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((l) => l());
}

export function getSteps(): PipelineStep[] {
  return steps;
}

export function isGenerating(): boolean {
  return generating;
}

export function isShowLog(): boolean {
  return showLog;
}

export function getHasRun(): boolean {
  return hasRun;
}

export function subscribe(cb: Listener): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

export function startGeneration() {
  steps = [];
  generating = true;
  showLog = true;
  hasRun = false;
  notify();
}

export function addPipelineStep(step: PipelineStep) {
  // Merge with existing step for same agent+ticker (update start → done)
  const existingIdx = steps.findIndex(
    (p) => p.step === step.step && p.ticker === step.ticker,
  );
  if (existingIdx >= 0) {
    const next = [...steps];
    // Preserve original timestamp to keep chronological ordering
    next[existingIdx] = { ...step, timestamp: next[existingIdx].timestamp };
    steps = next;
  } else {
    steps = [...steps, { ...step, timestamp: Date.now() }];
  }
  notify();
}

export function finishGeneration() {
  generating = false;
  hasRun = true;
  notify();
}

export function setShowLog(v: boolean) {
  showLog = v;
  notify();
}

export function clearSteps() {
  steps = [];
  notify();
}
