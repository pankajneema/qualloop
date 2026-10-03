'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useTranslations } from 'next-intl';

import { Button, buttonClass } from '@/components/button';
import { DataTable, type Column } from '@/components/data-table';
import { CheckboxField } from '@/components/field';
import { PageHeader } from '@/components/page-header';
import { ProblemAlert } from '@/components/problem-alert';
import { Badge, EmptyState, Skeleton } from '@/components/states';
import { canCommand, useMe } from '@/lib/session';
import type { Part } from '@/lib/types';
import { useKeyset } from '@/lib/use-keyset';

export default function PartsPage() {
  const t = useTranslations('parts');
  const common = useTranslations('common');
  const me = useMe();
  const [archived, setArchived] = useState(false);
  const list = useKeyset<Part>('/parts', {
    sort: 'part_no',
    archived: archived ? true : undefined,
  });

  const columns: Column<Part>[] = [
    {
      id: 'part_no',
      header: t('columns.partNo'),
      mono: true,
      cell: (p) => (
        <div>
          <Link
            href={`/parts/${p.id}`}
            className="text-body min-h-target sm:min-h-row inline-flex items-center font-mono underline"
          >
            {p.part_no}
          </Link>
          {p.archived_at ? <Badge>{t('archived')}</Badge> : null}
        </div>
      ),
    },
    { id: 'name', header: t('columns.name'), cell: (p) => p.name },
    {
      id: 'category',
      header: t('columns.category'),
      cell: (p) => p.category ?? '',
      hideOnPhone: true,
    },
    {
      id: 'revision',
      header: t('columns.revision'),
      cell: (p) => p.current_revision ?? '',
      hideOnPhone: true,
      mono: true,
    },
  ];
  const addLink = canCommand(me) ? (
    <Link href="/parts/new" className={buttonClass('primary')}>
      {t('add')}
    </Link>
  ) : null;

  return (
    <>
      <PageHeader title={t('title')} action={addLink} />
      <div className="mb-16">
        <CheckboxField
          label={t('showArchived')}
          checked={archived}
          onChange={(e) => setArchived(e.target.checked)}
        />
      </div>
      {list.error ? (
        <ProblemAlert
          error={list.error}
          actions={<Button onClick={list.reload}>{common('retry')}</Button>}
        />
      ) : list.loading && list.items.length === 0 ? (
        <Skeleton label={common('loading')} rows={6} />
      ) : list.items.length === 0 ? (
        <EmptyState title={t('empty.title')}>
          {canCommand(me) ? t('empty.body') : t('empty.viewerBody')}
        </EmptyState>
      ) : (
        <>
          <DataTable
            label={t('tableLabel')}
            columns={columns}
            rows={list.items}
            rowKey={(p) => p.id}
            dim={list.loading}
          />
          {list.hasMore ? (
            <div className="mt-16 flex justify-center">
              <Button onClick={list.loadMore} disabled={list.loadingMore}>
                {list.loadingMore ? common('loading') : common('loadMore')}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </>
  );
}
