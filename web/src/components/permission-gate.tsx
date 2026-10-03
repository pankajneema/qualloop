'use client';

import type { ReactNode } from 'react';
import { useTranslations } from 'next-intl';

import { PageHeader } from '@/components/page-header';
import { Alert } from '@/components/states';
import { canCommand, useMe } from '@/lib/session';

/** Imports are for Quality and Admin (API.md 3.3). The Viewer sees why, not a form that would only fail. */
export function ImportsGate({ title, children }: { title: string; children: ReactNode }) {
  const t = useTranslations('imports');
  const me = useMe();
  if (canCommand(me)) return <>{children}</>;
  return (
    <>
      <PageHeader title={title} />
      <Alert tone="warning" role="alert" title={t('noPermission.title')}>
        {t('noPermission.detail')}
      </Alert>
    </>
  );
}
