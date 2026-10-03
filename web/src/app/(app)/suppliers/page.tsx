'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';

import { buttonClass, Button } from '@/components/button';
import { DataTable, type Column } from '@/components/data-table';
import { CheckboxField, SelectField, TextField } from '@/components/field';
import { PageHeader } from '@/components/page-header';
import { ProblemAlert } from '@/components/problem-alert';
import { Badge, EmptyState, Skeleton } from '@/components/states';
import { StatusChip } from '@/components/status-chip';
import { canCommand, useMe } from '@/lib/session';
import {
  SUPPLIER_CATEGORIES,
  SUPPLIER_STATUSES,
  type Supplier,
  type SupplierCategory,
  type SupplierStatus,
} from '@/lib/types';
import { useFormatDate } from '@/lib/use-format';
import { useKeyset } from '@/lib/use-keyset';

type Sort = 'name' | 'code' | 'updated_at';

export default function SuppliersPage() {
  const t = useTranslations('suppliers');
  const common = useTranslations('common');
  const me = useMe();
  const formatDate = useFormatDate();

  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<'' | SupplierStatus>('');
  const [category, setCategory] = useState<'' | SupplierCategory>('');
  const [sort, setSort] = useState<Sort>('name');
  const [archived, setArchived] = useState(false);

  // Search waits for a pause in typing, so the list is not re-queried on every key.
  useEffect(() => {
    const timer = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const list = useKeyset<Supplier>('/suppliers', {
    q,
    status,
    category,
    sort,
    archived: archived ? true : undefined,
  });
  const filtered = Boolean(q || status || category || archived);

  const columns: Column<Supplier>[] = [
    {
      id: 'name',
      header: t('columns.name'),
      cell: (s) => (
        <div>
          <Link
            href={`/suppliers/${s.id}`}
            className="text-body min-h-target sm:min-h-row inline-flex items-center underline"
          >
            {s.name}
          </Link>
          <span className="text-data text-muted block font-mono sm:hidden">{s.code}</span>
          {s.archived_at ? <Badge>{t('archived')}</Badge> : null}
        </div>
      ),
    },
    { id: 'code', header: t('columns.code'), cell: (s) => s.code, hideOnPhone: true, mono: true },
    {
      id: 'category',
      header: t('columns.category'),
      cell: (s) => t(`category.${s.category}`),
      hideOnPhone: true,
    },
    { id: 'city', header: t('columns.city'), cell: (s) => s.city ?? '', hideOnPhone: true },
    {
      id: 'status',
      header: t('columns.status'),
      cell: (s) => (
        <StatusChip kind="supplier-status" value={s.status} label={t(`status.${s.status}`)} />
      ),
    },
    {
      id: 'updated',
      header: t('columns.updated'),
      cell: (s) => formatDate(s.updated_at),
      hideOnPhone: true,
    },
  ];

  return (
    <>
      <PageHeader
        title={t('title')}
        action={
          canCommand(me) ? (
            <Link href="/suppliers/new" className={buttonClass('primary')}>
              {t('add')}
            </Link>
          ) : null
        }
      />
      <div className="mb-16 grid gap-12 sm:grid-cols-2 lg:grid-cols-4">
        <div className="sm:col-span-2">
          <TextField
            label={t('search')}
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <SelectField
          label={t('filters.status')}
          value={status}
          onChange={(e) => setStatus(e.target.value as '' | SupplierStatus)}
        >
          <option value="">{t('filters.allStatuses')}</option>
          {SUPPLIER_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status.${s}`)}
            </option>
          ))}
        </SelectField>
        <SelectField
          label={t('filters.category')}
          value={category}
          onChange={(e) => setCategory(e.target.value as '' | SupplierCategory)}
        >
          <option value="">{t('filters.allCategories')}</option>
          {SUPPLIER_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {t(`category.${c}`)}
            </option>
          ))}
        </SelectField>
        <SelectField
          label={t('filters.sort')}
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
        >
          <option value="name">{t('sort.name')}</option>
          <option value="code">{t('sort.code')}</option>
          <option value="updated_at">{t('sort.updated_at')}</option>
        </SelectField>
        <CheckboxField
          label={t('filters.archived')}
          checked={archived}
          onChange={(e) => setArchived(e.target.checked)}
          className="sm:col-span-2 sm:self-end"
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
        filtered ? (
          <p className="text-body text-ink-2 py-16">{t('noMatch')}</p>
        ) : (
          <EmptyState
            title={t('empty.title')}
            action={
              canCommand(me) ? (
                <Link href="/imports/new" className={buttonClass('secondary')}>
                  {t('empty.import')}
                </Link>
              ) : null
            }
          >
            {canCommand(me) ? t('empty.body') : t('empty.viewerBody')}
          </EmptyState>
        )
      ) : (
        <>
          <DataTable
            label={t('tableLabel')}
            columns={columns}
            rows={list.items}
            rowKey={(s) => s.id}
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
