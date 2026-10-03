'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { Dialog } from '@/components/dialog';
import { PageHeader } from '@/components/page-header';
import { PartForm, type PartValues } from '@/components/part-form';
import { CustomerLinks, SupplierLinks } from '@/components/part-links';
import { ProblemAlert } from '@/components/problem-alert';
import { ReasonDialog } from '@/components/reason-dialog';
import { Alert, Skeleton } from '@/components/states';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import { canCommand, useMe } from '@/lib/session';
import type { Part } from '@/lib/types';
import { useAsync } from '@/lib/use-async';
import { useFormatDate } from '@/lib/use-format';

export default function PartPage() {
  const t = useTranslations('parts');
  const common = useTranslations('common');
  const reasonT = useTranslations('common.reason');
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const router = useRouter();
  const formatDate = useFormatDate();
  const part = useAsync<Part>(`part:${id}`, (signal) =>
    apiGet<Part>(`/parts/${id}`, undefined, signal),
  );
  const [dialog, setDialog] = useState<'edit' | 'archive' | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const commands = canCommand(me);

  async function save(values: PartValues) {
    const before = part.data;
    if (!before) return;
    const body: Record<string, string | null> = {};
    if (values.name.trim() !== before.name) body.name = values.name.trim();
    if (values.category.trim() !== (before.category ?? ''))
      body.category = values.category.trim() || null;
    if (values.current_revision.trim() !== (before.current_revision ?? '')) {
      body.current_revision = values.current_revision.trim() || null;
    }
    if (Object.keys(body).length > 0) await apiPost(`/parts/${id}/update`, body);
    setDialog(null);
    part.reload();
  }

  async function archive(reason: string) {
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(`/parts/${id}/archive`, { reason });
      setDialog(null);
      router.push('/parts');
    } catch (e) {
      setFailure(e instanceof ApiError ? e : new ApiError(0, null, null));
      setBusy(false);
    }
  }

  if (part.error) {
    return (
      <>
        <PageHeader title={t('detail.fallbackTitle')} />
        <ProblemAlert
          error={part.error}
          actions={<Button onClick={part.reload}>{common('retry')}</Button>}
        />
      </>
    );
  }
  const p = part.data;
  if (!p) {
    return (
      <>
        <PageHeader title={t('detail.fallbackTitle')} />
        <Skeleton label={common('loading')} />
      </>
    );
  }

  const details: { label: string; value: string; mono?: boolean }[] = [
    { label: t('form.partNo'), value: p.part_no, mono: true },
    { label: t('form.category'), value: p.category ?? '' },
    { label: t('form.revision'), value: p.current_revision ?? '', mono: true },
  ];

  return (
    <>
      <PageHeader
        title={p.name}
        action={
          commands && !p.archived_at ? (
            <Button onClick={() => setDialog('edit')}>{t('detail.edit')}</Button>
          ) : null
        }
      />
      {p.archived_at ? (
        <div className="mb-16">
          <Alert tone="info" role="status" title={t('detail.archivedTitle')}>
            {t('detail.archivedDetail', { date: formatDate(p.archived_at) })}
          </Alert>
        </div>
      ) : null}
      <section
        aria-labelledby="part-details"
        className="border-line-soft bg-surface rounded-card border p-16"
      >
        <h2 id="part-details" className="text-h2 text-ink">
          {t('detail.detailsHeading')}
        </h2>
        <dl className="mt-12 grid grid-cols-1 gap-12 sm:grid-cols-3">
          {details.map((d) => (
            <div key={d.label}>
              <dt className="text-label text-muted uppercase">{d.label}</dt>
              <dd
                className={`text-body text-ink-2 break-words ${d.mono ? 'text-data font-mono' : ''}`}
              >
                {d.value || <span className="text-muted">{t('detail.notSet')}</span>}
              </dd>
            </div>
          ))}
        </dl>
        {commands && !p.archived_at ? (
          <div className="mt-16">
            <Button variant="destructive" onClick={() => setDialog('archive')}>
              {t('archiveDialog.open')}
            </Button>
          </div>
        ) : null}
      </section>

      <SupplierLinks partId={p.id} canEdit={commands && !p.archived_at} />
      <CustomerLinks partId={p.id} canEdit={commands && !p.archived_at} />

      <Dialog
        open={dialog === 'edit'}
        title={t('editDialog.title')}
        onClose={() => setDialog(null)}
        footer={null}
      >
        <PartForm
          mode="edit"
          initial={{
            part_no: p.part_no,
            name: p.name,
            category: p.category ?? '',
            current_revision: p.current_revision ?? '',
          }}
          submitLabel={t('editDialog.submit')}
          onSubmit={save}
          onCancel={() => setDialog(null)}
        />
      </Dialog>
      <ReasonDialog
        open={dialog === 'archive'}
        title={t('archiveDialog.title')}
        consequence={t('archiveDialog.consequence')}
        reasonLabel={t('archiveDialog.reason')}
        actionLabel={t('archiveDialog.open')}
        cancelLabel={common('cancel')}
        busy={busy}
        destructive
        error={failure ? <ProblemAlert error={failure} /> : null}
        reasonErrors={{ required: reasonT('required'), too_long: reasonT('tooLong') }}
        onCancel={() => setDialog(null)}
        onConfirm={archive}
      />
    </>
  );
}
