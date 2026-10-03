'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

import { PageHeader } from '@/components/page-header';
import { PartForm, type PartValues } from '@/components/part-form';
import { Alert } from '@/components/states';
import { apiPost } from '@/lib/api';
import { canCommand, useMe } from '@/lib/session';
import type { Part } from '@/lib/types';

export default function NewPartPage() {
  const t = useTranslations('parts');
  const me = useMe();
  const router = useRouter();

  async function create(values: PartValues) {
    const created = await apiPost<Part>('/parts', {
      part_no: values.part_no.trim(),
      name: values.name.trim(),
      ...(values.category.trim() ? { category: values.category.trim() } : {}),
      ...(values.current_revision.trim()
        ? { current_revision: values.current_revision.trim() }
        : {}),
    });
    router.push(`/parts/${created.id}`);
  }

  return (
    <>
      <PageHeader title={t('new.title')} />
      {canCommand(me) ? (
        <PartForm
          mode="create"
          initial={{ part_no: '', name: '', category: '', current_revision: '' }}
          submitLabel={t('new.submit')}
          onSubmit={create}
        />
      ) : (
        <Alert tone="warning" title={t('noPermission.title')}>
          {t('noPermission.detail')}
        </Alert>
      )}
    </>
  );
}
