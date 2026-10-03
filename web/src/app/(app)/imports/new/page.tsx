'use client';

import { useTranslations } from 'next-intl';

import { ImportWizard } from '@/components/import-wizard';
import { ImportsGate } from '@/components/permission-gate';
import { PageHeader } from '@/components/page-header';

export default function NewImportPage() {
  const t = useTranslations('imports');
  return (
    <ImportsGate title={t('new')}>
      <PageHeader title={t('new')} />
      <ImportWizard />
    </ImportsGate>
  );
}
