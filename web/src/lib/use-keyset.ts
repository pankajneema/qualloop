'use client';

import { useCallback, useEffect, useState } from 'react';

import { apiGet, ApiError } from '@/lib/api';
import type { Page } from '@/lib/types';

type Query = Record<string, string | number | boolean | null | undefined>;

type State<T> = {
  key: string;
  items: T[];
  nextCursor: string | null;
  error: ApiError | null;
  loadingMore: boolean;
};

export type Keyset<T> = {
  items: T[];
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: ApiError | null;
  loadMore: () => void;
  reload: () => void;
};

/**
 * Keyset list (API.md 1.5): the first page loads whenever the path or query changes, "Load more" appends the next one
 * with the opaque cursor. The previous rows stay on screen while a new query loads.
 */
export function useKeyset<T>(path: string, query: Query, pageSize = 50): Keyset<T> {
  const key = JSON.stringify([path, query, pageSize]);
  const [tick, setTick] = useState(0);
  const fullKey = `${key}#${tick}`;
  const [state, setState] = useState<State<T> | null>(null);
  const [cursorRequest, setCursorRequest] = useState<{ key: string; cursor: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<Page<T>>(path, { ...query, limit: pageSize }, controller.signal).then(
      (page) =>
        setState({
          key: fullKey,
          items: page.items,
          nextCursor: page.next_cursor,
          error: null,
          loadingMore: false,
        }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          key: fullKey,
          items: [],
          nextCursor: null,
          error: error instanceof ApiError ? error : new ApiError(0, null, null),
          loadingMore: false,
        });
      },
    );
    return () => controller.abort();
    // the query object is re-created on every render; `fullKey` is its serialised form
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullKey]);

  useEffect(() => {
    if (!cursorRequest || cursorRequest.key !== fullKey) return;
    const controller = new AbortController();
    apiGet<Page<T>>(
      path,
      { ...query, limit: pageSize, cursor: cursorRequest.cursor },
      controller.signal,
    ).then(
      (page) =>
        setState((prev) =>
          prev && prev.key === fullKey
            ? {
                ...prev,
                items: [...prev.items, ...page.items],
                nextCursor: page.next_cursor,
                loadingMore: false,
                error: null,
              }
            : prev,
        ),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState((prev) =>
          prev && prev.key === fullKey
            ? {
                ...prev,
                loadingMore: false,
                error: error instanceof ApiError ? error : new ApiError(0, null, null),
              }
            : prev,
        );
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursorRequest]);

  const current = state && state.key === fullKey ? state : null;
  const loadMore = useCallback(() => {
    if (!current?.nextCursor || current.loadingMore) return;
    setState({ ...current, loadingMore: true });
    setCursorRequest({ key: fullKey, cursor: current.nextCursor });
  }, [current, fullKey]);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  return {
    items: (current ?? state)?.items ?? [],
    hasMore: Boolean(current?.nextCursor),
    loading: current === null,
    loadingMore: current?.loadingMore ?? false,
    error: current?.error ?? null,
    loadMore,
    reload,
  };
}
