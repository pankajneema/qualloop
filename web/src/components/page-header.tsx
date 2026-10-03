'use client';

import { useEffect, type ReactNode } from 'react';

/** One h1 per screen and at most one primary action (DESIGN_SPEC). Also names the browser tab. */
export function PageHeader({ title, action }: { title: string; action?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · QualLoop`;
  }, [title]);
  return (
    <header className="mb-24 flex flex-wrap items-center justify-between gap-12">
      <h1 className="text-h1 text-ink min-w-0 break-words">{title}</h1>
      {action ? <div className="flex flex-wrap gap-8">{action}</div> : null}
    </header>
  );
}
