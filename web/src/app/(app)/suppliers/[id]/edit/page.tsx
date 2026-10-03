'use client';

import { useParams, useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { PageHeader } from '@/components/page-header';
import { ProblemAlert } from '@/components/problem-alert';
import { Alert, Skeleton } from '@/components/states';
import {
  SupplierForm,
  valuesFromSupplier,
  type SupplierFormValues,
} from '@/components/supplier-form';
import { apiGet, apiPost } from '@/lib/api';
import { canCommand, useMe } from '@/lib/session';
import type { Supplier } from '@/lib/types';
import { useAsync } from '@/lib/use-async';

export default function EditSupplierPage() {
  const t = useTranslations('suppliers');
  const common = useTranslations('common');
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const router = useRouter();
  const supplier = useAsync<Supplier>(`supplier:${id}`, (signal) =>
    apiGet<Supplier>(`/suppliers/${id}`, undefined, signal),
  );

  async function save(values: SupplierFormValues) {
    const before = supplier.data;
    if (!before) return;
    const body: Record<string, string | null> = {};
    const text = (v: string) => v.trim();
    if (text(values.code) !== before.code) body.code = text(values.code);
    if (text(values.name) !== before.name) body.name = text(values.name);
    if (values.category && values.category !== before.category) body.category = values.category;
    for (const field of ['gstin', 'city', 'state'] as const) {
      const next = text(values[field]);
      if (next !== (before[field] ?? '')) body[field] = next || null;
    }
    if (Object.keys(body).length > 0) await apiPost(`/suppliers/${id}/update`, body);
    router.push(`/suppliers/${id}`);
  }

  if (!canCommand(me)) {
    return (
      <>
        <PageHeader title={t('edit.title')} />
        <Alert tone="warning" title={t('noPermission.title')}>
          {t('noPermission.detail')}
        </Alert>
      </>
    );
  }
  if (supplier.error) {
    return (
      <>
        <PageHeader title={t('edit.title')} />
        <ProblemAlert
          error={supplier.error}
          actions={<Button onClick={supplier.reload}>{common('retry')}</Button>}
        />
      </>
    );
  }
  if (!supplier.data) {
    return (
      <>
        <PageHeader title={t('edit.title')} />
        <Skeleton label={common('loading')} />
      </>
    );
  }
  return (
    <>
      <PageHeader title={t('edit.titleFor', { name: supplier.data.name })} />
      <SupplierForm
        mode="edit"
        initial={valuesFromSupplier(supplier.data)}
        canChooseStatus={false}
        submitLabel={t('edit.submit')}
        onSubmit={save}
      />
    </>
  );
}
