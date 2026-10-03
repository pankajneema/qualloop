'use client';

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '@/lib/api';

type State<T> =
  { key: string; status: 'ok'; data: T } | { key: string; status: 'error'; error: ApiError } | null;

export type Async<T> = {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
};

/** Loads on mount and whenever `key` changes; an older answer never overwrites a newer request. */
export function useAsync<T>(key: string, load: (signal: AbortSignal) => Promise<T>): Async<T> {
  const [state, setState] = useState<State<T>>(null);
  const [tick, setTick] = useState(0);
  const fullKey = `${key}#${tick}`;

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => setState({ key: fullKey, status: 'ok', data }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          key: fullKey,
          status: 'error',
          error: error instanceof ApiError ? error : new ApiError(0, null, null),
        });
      },
    );
    return () => controller.abort();
    // `load` is re-created on every render by design; `key` names what it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullKey]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const current = state && state.key === fullKey ? state : null;
  const stale = state && state.status === 'ok' && !current ? state.data : null;
  return {
    data: current?.status === 'ok' ? current.data : stale,
    error: current?.status === 'error' ? current.error : null,
    loading: current === null,
    reload,
  };
}
