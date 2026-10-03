'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { useTranslations } from 'next-intl';

import { Button, buttonClass } from '@/components/button';
import { ContactsSection } from '@/components/contacts-section';
import { SelectField } from '@/components/field';
import { PageHeader } from '@/components/page-header';
import { ProblemAlert } from '@/components/problem-alert';
import { ReasonDialog } from '@/components/reason-dialog';
import { Alert, Skeleton } from '@/components/states';
import { StatusChip } from '@/components/status-chip';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import { canCommand, useMe } from '@/lib/session';
import { SUPPLIER_STATUSES, type Supplier, type SupplierStatus } from '@/lib/types';
import { useAsync } from '@/lib/use-async';
import { useFormatDate } from '@/lib/use-format';

type Dialog = 'status' | 'archive' | null;

export default function SupplierPage() {
  const t = useTranslations('suppliers');
  const common = useTranslations('common');
  const reasonT = useTranslations('common.reason');
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const router = useRouter();
  const formatDate = useFormatDate();
  const supplier = useAsync<Supplier>(`supplier:${id}`, (signal) =>
    apiGet<Supplier>(`/suppliers/${id}`, undefined, signal),
  );
  const [dialog, setDialog] = useState<Dialog>(null);
  const [nextStatus, setNextStatus] = useState<'' | SupplierStatus>('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);

  function close() {
    setDialog(null);
    setNextStatus('');
    setFailure(null);
  }

  async function run(path: string, body: unknown, after: () => void) {
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(path, body);
      after();
    } catch (e) {
      setFailure(e instanceof ApiError ? e : new ApiError(0, null, null));
    } finally {
      setBusy(false);
    }
  }

  if (supplier.error) {
    return (
      <>
        <PageHeader title={t('detail.fallbackTitle')} />
        <ProblemAlert
          error={supplier.error}
          actions={<Button onClick={supplier.reload}>{common('retry')}</Button>}
        />
      </>
    );
  }
  const s = supplier.data;
  if (!s) {
    return (
      <>
        <PageHeader title={t('detail.fallbackTitle')} />
        <Skeleton label={common('loading')} />
      </>
    );
  }

  const commands = canCommand(me);
  const reasonErrors = { required: reasonT('required'), too_long: reasonT('tooLong') };
  const errorBlock = failure ? <ProblemAlert error={failure} /> : null;
  const details: { label: string; value: string; mono?: boolean }[] = [
    { label: t('form.code'), value: s.code, mono: true },
    { label: t('form.gstin'), value: s.gstin ?? '', mono: true },
    { label: t('form.city'), value: s.city ?? '' },
    { label: t('form.state'), value: s.state ?? '' },
    { label: t('form.category'), value: t(`category.${s.category}`) },
    { label: t('detail.updated'), value: formatDate(s.updated_at) },
  ];

  return (
    <>
      <PageHeader
        title={s.name}
        action={
          commands ? (
            <Link href={`/suppliers/${s.id}/edit`} className={buttonClass('secondary')}>
              {t('detail.edit')}
            </Link>
          ) : null
        }
      />
      {s.archived_at ? (
        <div className="mb-16">
          <Alert tone="info" role="status" title={t('detail.archivedTitle')}>
            {t('detail.archivedDetail', { date: formatDate(s.archived_at) })}
          </Alert>
        </div>
      ) : null}

      <div className="grid gap-16 lg:grid-cols-2">
        <section
          aria-labelledby="status-heading"
          className="border-line-soft bg-surface rounded-card border p-16"
        >
          <h2 id="status-heading" className="text-h2 text-ink">
            {t('detail.statusHeading')}
          </h2>
          <div className="mt-12 flex flex-wrap items-center gap-12">
            <StatusChip kind="supplier-status" value={s.status} label={t(`status.${s.status}`)} />
            {s.status_changed_at ? (
              <span className="text-caption text-muted">
                {t('detail.statusChanged', { date: formatDate(s.status_changed_at) })}
              </span>
            ) : null}
          </div>
          {s.status_reason ? (
            <dl className="mt-12">
              <dt className="text-label text-muted uppercase">{t('detail.statusReason')}</dt>
              <dd className="text-body text-ink-2 break-words">{s.status_reason}</dd>
            </dl>
          ) : null}
          {commands ? (
            <div className="mt-16">
              <Button onClick={() => setDialog('status')} disabled={!me.can_approve}>
                {t('statusDialog.title')}
              </Button>
              {!me.can_approve ? (
                <p className="text-caption text-muted mt-4">{t('detail.onlyApprovers')}</p>
              ) : null}
            </div>
          ) : null}
        </section>

        <section
          aria-labelledby="details-heading"
          className="border-line-soft bg-surface rounded-card border p-16"
        >
          <h2 id="details-heading" className="text-h2 text-ink">
            {t('detail.detailsHeading')}
          </h2>
          <dl className="mt-12 grid grid-cols-2 gap-x-16 gap-y-12">
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
          {commands && !s.archived_at ? (
            <div className="mt-16">
              <Button variant="destructive" onClick={() => setDialog('archive')}>
                {t('archiveDialog.open')}
              </Button>
            </div>
          ) : null}
        </section>
      </div>

      <ContactsSection supplierId={s.id} canEdit={commands} />

      <ReasonDialog
        open={dialog === 'status'}
        title={t('statusDialog.title')}
        consequence={t('statusDialog.consequence')}
        reasonLabel={t('statusDialog.reason')}
        actionLabel={t('statusDialog.title')}
        cancelLabel={common('cancel')}
        extraInvalid={!nextStatus}
        busy={busy}
        error={errorBlock}
        reasonErrors={reasonErrors}
        onCancel={close}
        onConfirm={(reason) =>
          run(`/suppliers/${s.id}/change-status`, { status: nextStatus, reason }, () => {
            close();
            supplier.reload();
          })
        }
      >
        <SelectField
          label={t('statusDialog.newStatus')}
          value={nextStatus}
          onChange={(e) => setNextStatus(e.target.value as '' | SupplierStatus)}
        >
          <option value="">{t('form.statusPlaceholder')}</option>
          {SUPPLIER_STATUSES.filter((x) => x !== s.status).map((x) => (
            <option key={x} value={x}>
              {t(`status.${x}`)}
            </option>
          ))}
        </SelectField>
      </ReasonDialog>

      <ReasonDialog
        open={dialog === 'archive'}
        title={t('archiveDialog.title')}
        consequence={t('archiveDialog.consequence')}
        reasonLabel={t('archiveDialog.reason')}
        actionLabel={t('archiveDialog.open')}
        cancelLabel={common('cancel')}
        busy={busy}
        error={errorBlock}
        destructive
        reasonErrors={reasonErrors}
        onCancel={close}
        onConfirm={(reason) =>
          run(`/suppliers/${s.id}/archive`, { reason }, () => {
            close();
            router.push('/suppliers');
          })
        }
      />
    </>
  );
}
