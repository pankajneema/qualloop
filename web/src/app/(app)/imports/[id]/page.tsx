'use client';

import { useParams } from 'next/navigation';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { ImportWizard } from '@/components/import-wizard';
import { ImportsGate } from '@/components/permission-gate';
import { PageHeader } from '@/components/page-header';
import { ProblemAlert } from '@/components/problem-alert';
import { Skeleton } from '@/components/states';
import { apiGet } from '@/lib/api';
import type { ImportBatch } from '@/lib/types';
import { useAsync } from '@/lib/use-async';

/** Opens an existing batch at the step its status says (a finished one shows its result and report). */
export default function ImportPage() {
  const t = useTranslations('imports');
  const common = useTranslations('common');
  const { id } = useParams<{ id: string }>();
  return (
    <ImportsGate title={t('detail.title')}>
      <Loaded id={id} retry={common('retry')} loading={common('loading')} />
    </ImportsGate>
  );
}

function Loaded({ id, retry, loading }: { id: string; retry: string; loading: string }) {
  const t = useTranslations('imports');
  const batch = useAsync<ImportBatch>(`import:${id}`, (signal) =>
    apiGet<ImportBatch>(`/imports/${id}`, undefined, signal),
  );
  return (
    <>
      <PageHeader title={batch.data ? batch.data.file_name : t('detail.title')} />
      {batch.error ? (
        <ProblemAlert
          error={batch.error}
          actions={<Button onClick={batch.reload}>{retry}</Button>}
        />
      ) : batch.data ? (
        <ImportWizard initialBatch={batch.data} />
      ) : (
        <Skeleton label={loading} />
      )}
    </>
  );
}
