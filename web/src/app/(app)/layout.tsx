'use client';

import type { ReactNode } from 'react';

import { AppShell } from '@/components/app-shell';
import { SessionProvider } from '@/lib/session';

/** Everything behind the sign-in: the session, then the shell (nav, bottom bar). */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
