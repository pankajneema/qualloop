import type { ReactNode } from 'react';

import { LocaleSwitch } from '@/components/locale-switch';

/** Frame for the signed-out screens: the brand, the language toggle and one centred card. */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen px-16 py-24">
      <div className="mx-auto flex max-w-md items-center justify-between">
        <span className="text-h2 text-ink">QualLoop</span>
        <LocaleSwitch />
      </div>
      <main className="bg-surface border-line-soft rounded-card mx-auto mt-24 max-w-md border p-16 sm:p-24">
        {children}
      </main>
    </div>
  );
}
