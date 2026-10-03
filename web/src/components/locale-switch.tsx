'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';

import { locales, setLocaleCookie, type Locale } from '@/i18n/config';

const NAMES: Record<Locale, string> = { en: 'English', hi: 'हिन्दी' };

/** EN / हिन्दी toggle. The choice lives in the `ql_locale` cookie that src/i18n/request.ts reads. */
export function LocaleSwitch({ onDark = false }: { onDark?: boolean }) {
  const current = useLocale();
  const router = useRouter();
  const t = useTranslations('common');

  function choose(locale: Locale) {
    setLocaleCookie(locale);
    router.refresh();
  }

  return (
    <div role="group" aria-label={t('language')} className="flex gap-4">
      {locales.map((locale) => (
        <button
          key={locale}
          type="button"
          lang={locale}
          aria-pressed={current === locale}
          onClick={() => choose(locale)}
          className={`text-body min-h-target rounded-control px-12 ${
            current === locale
              ? onDark
                ? 'bg-ink-2 text-surface'
                : 'bg-line-soft text-ink'
              : onDark
                ? 'text-surface'
                : 'text-action'
          }`}
        >
          {NAMES[locale]}
        </button>
      ))}
    </div>
  );
}
