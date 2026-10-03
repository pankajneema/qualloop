'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState, type ReactNode } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { LocaleSwitch } from '@/components/locale-switch';
import { apiPost } from '@/lib/api';
import { useMe } from '@/lib/session';

const LINKS = [
  { href: '/suppliers', key: 'suppliers', quality: false },
  { href: '/parts', key: 'parts', quality: false },
  { href: '/imports', key: 'imports', quality: true },
] as const;

/**
 * Dark left nav (232 px) from 640 px up, a bottom bar below it (DESIGN_SPEC). The Viewer is not offered Imports:
 * the API refuses it, and a link that only ends in an error teaches nothing.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations('common');
  const me = useMe();
  const pathname = usePathname();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    try {
      await apiPost('/auth/logout', {});
    } catch {
      // The cookie may already be gone; the sign-in screen is the right place either way.
    }
    router.replace('/login');
    router.refresh();
  }

  const links = LINKS.filter((l) => !l.quality || me.role !== 'viewer');

  const account = (
    <div className="flex flex-col gap-8">
      <p className="text-caption text-line break-words">{me.name}</p>
      <LocaleSwitch onDark />
      <Button variant="secondary" onClick={signOut} disabled={signingOut} className="w-full">
        {t('signOut')}
      </Button>
    </div>
  );

  return (
    <div className="min-h-screen sm:flex">
      <a
        href="#main"
        className="bg-surface text-ink rounded-control sr-only z-50 p-12 focus:not-sr-only focus:fixed focus:top-8 focus:left-8"
      >
        {t('skipToContent')}
      </a>
      <nav
        aria-label={t('nav.label')}
        className="bg-ink text-surface fixed inset-x-0 bottom-0 z-40 flex border-t border-ink-2 sm:sticky sm:top-0 sm:h-screen sm:w-nav sm:shrink-0 sm:flex-col sm:justify-between sm:border-t-0 sm:px-16 sm:py-24"
      >
        <div className="flex w-full sm:flex-col sm:gap-24">
          <span className="text-h2 hidden sm:block">QualLoop</span>
          <ul className="flex w-full sm:flex-col sm:gap-4">
            {links.map((l) => {
              const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
              return (
                <li key={l.href} className="flex-1 sm:flex-none">
                  <Link
                    href={l.href}
                    aria-current={active ? 'page' : undefined}
                    className={`text-h3 min-h-target rounded-control flex items-center justify-center px-12 py-8 text-center sm:justify-start ${
                      active ? 'bg-ink-2 text-surface' : 'text-surface hover:bg-ink-2'
                    }`}
                  >
                    {t(`nav.${l.key}`)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="hidden sm:block">{account}</div>
      </nav>
      <div className="min-w-0 flex-1">
        <details className="bg-ink text-surface px-16 py-4 sm:hidden">
          <summary className="min-h-target flex cursor-pointer items-center justify-between gap-8">
            <span className="text-h2">QualLoop</span>
            <span className="text-h3">{me.name}</span>
          </summary>
          <div className="pt-8 pb-12">{account}</div>
        </details>
        <main id="main" tabIndex={-1} className="max-w-content mx-auto px-16 py-24 sm:px-32">
          {children}
        </main>
      </div>
    </div>
  );
}
