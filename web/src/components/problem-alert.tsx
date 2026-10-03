'use client';

import type { ReactNode } from 'react';

import { Alert } from '@/components/states';
import { useDescribe } from '@/lib/use-problem';

/** An API failure as "what happened, what we did, what you can do" (DESIGN_SPEC copy rules). */
export function ProblemAlert({ error, actions }: { error: unknown; actions?: ReactNode }) {
  const describe = useDescribe();
  const d = describe(error);
  return (
    <Alert tone="error" title={d.title} actions={actions}>
      {d.detail}
    </Alert>
  );
}
