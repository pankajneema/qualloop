'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

import { PageHeader } from '@/components/page-header';
import { Alert } from '@/components/states';
import { EMPTY_SUPPLIER, SupplierForm, type SupplierFormValues } from '@/components/supplier-form';
import { apiPost } from '@/lib/api';
import { canCommand, useMe } from '@/lib/session';
import type { Supplier } from '@/lib/types';

export default function NewSupplierPage() {
  const t = useTranslations('suppliers');
  const me = useMe();
  const router = useRouter();

  async function create(values: SupplierFormValues) {
    const created = await apiPost<Supplier>('/suppliers', {
      code: values.code.trim(),
      name: values.name.trim(),
      category: values.category,
      status: values.status,
      ...(values.gstin ? { gstin: values.gstin } : {}),
      ...(values.city.trim() ? { city: values.city.trim() } : {}),
      ...(values.state.trim() ? { state: values.state.trim() } : {}),
    });
    router.push(`/suppliers/${created.id}`);
  }

  if (!canCommand(me)) {
    return (
      <>
        <PageHeader title={t('new.title')} />
        <Alert tone="warning" title={t('noPermission.title')}>
          {t('noPermission.detail')}
        </Alert>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t('new.title')} />
      <SupplierForm
        mode="create"
        initial={EMPTY_SUPPLIER}
        canChooseStatus={me.can_approve}
        submitLabel={t('new.submit')}
        onSubmit={create}
      />
    </>
  );
}
