import { getTranslations } from 'next-intl/server';

export default async function HomePage() {
  const t = await getTranslations();
  return (
    <div className="flex min-h-screen">
      <nav
        aria-label={t('shell.navLabel')}
        className="w-nav bg-ink text-surface shrink-0 px-16 py-24"
        data-testid="app-nav"
      >
        <span className="text-h2">QualLoop</span>
      </nav>
      <main aria-label={t('shell.mainLabel')} className="max-w-content flex-1 px-32 py-24">
        <h1 className="text-h1 text-ink">{t('home.title')}</h1>
        <p className="text-body text-muted mt-8">{t('home.subtitle')}</p>
      </main>
    </div>
  );
}
