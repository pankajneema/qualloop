'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';

import { Button, buttonClass } from '@/components/button';
import { DataTable, type Column } from '@/components/data-table';
import { ImportsGate } from '@/components/permission-gate';
import { PageHeader } from '@/components/page-header';
import { ProblemAlert } from '@/components/problem-alert';
import { EmptyState, Skeleton } from '@/components/states';
import type { ImportBatch } from '@/lib/types';
import { useFormatDate } from '@/lib/use-format';
import { useKeyset } from '@/lib/use-keyset';

export default function ImportsPage() {
  const t = useTranslations('imports');
  return (
    <ImportsGate title={t('title')}>
      <ImportsList />
    </ImportsGate>
  );
}

function ImportsList() {
  const t = useTranslations('imports');
  const common = useTranslations('common');
  const formatDate = useFormatDate();
  const list = useKeyset<ImportBatch>('/imports', {});

  const columns: Column<ImportBatch>[] = [
    {
      id: 'file',
      header: t('columns.file'),
      cell: (b) => (
        <Link
          href={`/imports/${b.id}`}
          className="text-body min-h-target sm:min-h-row inline-flex items-center break-all underline"
        >
          {b.file_name}
        </Link>
      ),
    },
    { id: 'entity', header: t('columns.entity'), cell: (b) => t(`entity.${b.entity}`) },
    { id: 'status', header: t('columns.status'), cell: (b) => t(`status.${b.status}`) },
    {
      id: 'rows',
      header: t('columns.rows'),
      cell: (b) => `${b.rows_imported} / ${b.rows_received}`,
      mono: true,
      hideOnPhone: true,
    },
    {
      id: 'date',
      header: t('columns.date'),
      cell: (b) => formatDate(b.created_at),
      hideOnPhone: true,
    },
  ];

  const newLink = (
    <Link href="/imports/new" className={buttonClass('primary')}>
      {t('new')}
    </Link>
  );

  return (
    <>
      <PageHeader title={t('title')} action={newLink} />
      {list.error ? (
        <ProblemAlert
          error={list.error}
          actions={<Button onClick={list.reload}>{common('retry')}</Button>}
        />
      ) : list.loading && list.items.length === 0 ? (
        <Skeleton label={common('loading')} rows={5} />
      ) : list.items.length === 0 ? (
        <EmptyState title={t('empty.title')}>{t('empty.body')}</EmptyState>
      ) : (
        <>
          <DataTable
            label={t('tableLabel')}
            columns={columns}
            rows={list.items}
            rowKey={(b) => b.id}
            dim={list.loading}
          />
          {list.hasMore ? (
            <div className="mt-16 flex justify-center">
              <Button onClick={list.loadMore} disabled={list.loadingMore}>
                {common('loadMore')}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </>
  );
}
