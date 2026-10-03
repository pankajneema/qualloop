'use client';

import { createContext, useContext, type ReactNode } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { ProblemAlert } from '@/components/problem-alert';
import { Skeleton } from '@/components/states';
import { apiGet } from '@/lib/api';
import type { Me } from '@/lib/types';
import { useAsync } from '@/lib/use-async';

const SessionContext = createContext<Me | null>(null);

/** Loads `/me` once for the signed-in screens. A 401 sends the browser to /login (see lib/api.ts). */
export function SessionProvider({ children }: { children: ReactNode }) {
  const t = useTranslations('common');
  const me = useAsync<Me>('me', (signal) => apiGet<Me>('/me', undefined, signal));
  if (me.data) return <SessionContext.Provider value={me.data}>{children}</SessionContext.Provider>;
  if (me.error) {
    return (
      <div className="p-24">
        <ProblemAlert
          error={me.error}
          actions={<Button onClick={me.reload}>{t('retry')}</Button>}
        />
      </div>
    );
  }
  return (
    <div className="p-24">
      <Skeleton label={t('loading')} />
    </div>
  );
}

export function useMe(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error('useMe must be used inside SessionProvider');
  return me;
}

/** The plant's timezone for dates ("3 Oct 2026"); India Standard Time until a plant says otherwise. */
export function usePlantTimeZone(): string {
  return useMe().plants[0]?.timezone ?? 'Asia/Kolkata';
}

export function canCommand(me: Me): boolean {
  return me.role !== 'viewer';
}
