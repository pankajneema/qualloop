import type { CSSProperties, ReactNode } from 'react';
import { NextIntlClientProvider } from 'next-intl';
import { getLocale } from 'next-intl/server';

import { cssVariables } from '@/design/tokens';
import { plexDevanagari, plexMono, plexSans } from '@/design/fonts';

import './globals.css';

export const metadata = { title: 'QualLoop' };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  return (
    <html
      lang={locale}
      className={`${plexSans.variable} ${plexDevanagari.variable} ${plexMono.variable}`}
      style={cssVariables as CSSProperties}
    >
      <body className="bg-ground text-ink-2 min-h-screen">
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
