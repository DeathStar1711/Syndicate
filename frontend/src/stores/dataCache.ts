/**
 * Global data cache with stale-while-revalidate semantics.
 *
 * - Persists across route changes (singleton outside React tree).
 * - Shows stale data instantly; refreshes in background.
 * - Deduplicates: only one in-flight fetch per key at a time.
 */
import { useSyncExternalStore, useCallback, useRef, useEffect } from 'react';

// ── Types ────────────────────────────────────────────
type CacheEntry<T = unknown> = {
  data: T | null;
  fetchedAt: number;       // epoch ms
  isFetching: boolean;
  fetchId: number;          // monotonic — guards stale responses
  error: string | null;
};

type Listener = () => void;

// ── Singleton store ──────────────────────────────────
const cache = new Map<string, CacheEntry>();
const listeners = new Set<Listener>();
let globalFetchId = 0;

function notify() {
  listeners.forEach((l) => l());
}

function getEntry<T>(key: string): CacheEntry<T> {
  let entry = cache.get(key) as CacheEntry<T> | undefined;
  if (!entry) {
    entry = {
      data: null,
      fetchedAt: 0,
      isFetching: false,
      fetchId: 0,
      error: null,
    };
    cache.set(key, entry as CacheEntry);
  }
  return entry;
}

function setEntry<T>(key: string, patch: Partial<CacheEntry<T>>) {
  const prev = getEntry<T>(key);
  cache.set(key, { ...prev, ...patch } as CacheEntry);
  notify();
}

/** Trigger a fetch for a given key. Deduplicates in-flight requests. */
function triggerFetch<T>(key: string, fetcher: () => Promise<T>) {
  const entry = getEntry<T>(key);
  if (entry.isFetching) return;  // Already in-flight

  const myId = ++globalFetchId;
  setEntry<T>(key, { isFetching: true, fetchId: myId, error: null });

  fetcher()
    .then((result) => {
      const current = getEntry<T>(key);
      if (current.fetchId === myId) {
        setEntry<T>(key, {
          data: result,
          fetchedAt: Date.now(),
          isFetching: false,
          error: null,
        });
      }
    })
    .catch((err) => {
      const current = getEntry<T>(key);
      if (current.fetchId === myId) {
        setEntry<T>(key, {
          isFetching: false,
          fetchedAt: Date.now(), // Prevent infinite retry loop on error
          error: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    });
}

/** Invalidate a key (forces fresh fetch on next access). */
export function invalidateCache(key: string) {
  const entry = getEntry(key);
  cache.set(key, { ...entry, fetchedAt: 0 } as CacheEntry);
  notify();
}

/** Read current cached data for a key (no React — for one-off reads). */
export function readCache<T>(key: string): T | null {
  return getEntry<T>(key).data;
}

// ── React hook ───────────────────────────────────────

/**
 * useCachedApi — drop-in replacement for `useApi` that reads from
 * the global cache.  Shows stale data immediately, refreshes in the
 * background when the entry is older than `staleMs`.
 *
 * @param key      Unique cache key ('portfolio', 'signals', …)
 * @param fetcher  Async function that returns the data
 * @param staleMs  How many ms before the entry is considered stale
 *                 (default 30 000 = 30 s)
 */
export function useCachedApi<T>(
  key: string,
  fetcher: () => Promise<T>,
  staleMs = 30_000,
) {
  // Keep a stable ref to fetcher so we never re-subscribe
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Subscribe to the singleton store
  const subscribe = useCallback((cb: Listener) => {
    listeners.add(cb);
    return () => { listeners.delete(cb); };
  }, []);

  const getSnapshot = useCallback(() => getEntry<T>(key), [key]);

  const entry = useSyncExternalStore(subscribe, getSnapshot);

  // Check if we need to fetch immediately
  const hasData = entry.data !== null;
  const isStale = Date.now() - entry.fetchedAt > staleMs;
  const shouldFetch = (!hasData || isStale) && !entry.isFetching;

  // Trigger fetch in useEffect (not during render) to avoid React warnings
  useEffect(() => {
    if (shouldFetch) {
      triggerFetch<T>(key, fetcherRef.current);
    }
  }, [key, shouldFetch]);

  // Set up polling to check for staleness periodically
  useEffect(() => {
    const interval = setInterval(() => {
      const currentEntry = getEntry<T>(key);
      const currentlyStale = Date.now() - currentEntry.fetchedAt > staleMs;
      if (currentlyStale && !currentEntry.isFetching) {
        triggerFetch<T>(key, fetcherRef.current);
      }
    }, Math.min(staleMs, 10000)); // check at least every 10s or staleMs
    return () => clearInterval(interval);
  }, [key, staleMs]);

  /** Force a fresh fetch right now (e.g. after a mutation). */
  const refetch = useCallback(() => {
    invalidateCache(key);
  }, [key]);

  return {
    data: entry.data,
    loading: !hasData && entry.isFetching,   // only block UI when there's NO cached data
    refreshing: hasData && entry.isFetching,  // subtle indicator for background refresh
    error: entry.error,
    refetch,
  };
}
