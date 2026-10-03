'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';

import { Button, buttonClass } from '@/components/button';
import { DataTable, type Column } from '@/components/data-table';
import { CheckboxField, SelectField } from '@/components/field';
import { ImportSteps } from '@/components/import-steps';
import { ProblemAlert } from '@/components/problem-alert';
import { Progress } from '@/components/progress';
import { Alert, EmptyState, Skeleton } from '@/components/states';
import { Tabs } from '@/components/tabs';
import { API_BASE, apiGet, apiPost, ApiError } from '@/lib/api';
import { formatIndianNumber } from '@/lib/format';
import { newIdempotencyKey } from '@/lib/http';
import {
  canConfirm,
  missingRequiredFields,
  needsPartialConfirmation,
  reconciles,
  type WizardStep,
} from '@/lib/import-wizard';
import {
  IMPORT_ENTITIES,
  type ImportBatch,
  type ImportEntity,
  type PreviewRow,
  type PreviewStatus,
} from '@/lib/types';
import { useKeyset } from '@/lib/use-keyset';

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const MAX_BYTES = 20_000_000; // the API refuses more (A-97); said here to save a slow upload
const SCAN_RETRIES = 28; // the virus scan promotes the file; POST /imports answers 404 until it has
const SCAN_WAIT_MS = 2_000;
const POLL_MS = 1_000;
const POLL_LIMIT_MS = 180_000;

type Tone = { kind: 'api'; error: ApiError } | { kind: 'text'; title: string; detail: string };

const TAB_STATUS: Record<string, PreviewStatus> = {
  errors: 'rejected',
  duplicates: 'duplicate',
  unmapped: 'unmapped',
  review: 'review',
  valid: 'valid',
};

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stepOf(batch: ImportBatch | null, validating: boolean, confirming: boolean): WizardStep {
  if (!batch) return 'upload';
  switch (batch.status) {
    case 'uploaded':
      return 'map';
    case 'mapped':
      return validating ? 'validate' : 'map';
    case 'validated':
      return confirming ? 'confirm' : 'preview';
    case 'importing':
      return 'confirm';
    case 'completed':
    case 'failed':
    case 'cancelled':
      return 'result';
  }
}

function SummaryRegion({
  batch,
  label,
  includeImported,
}: {
  batch: ImportBatch;
  label: string;
  includeImported: boolean;
}) {
  const t = useTranslations('imports.summary');
  const items: [string, number][] = [
    [t('received'), batch.rows_received],
    ...(includeImported ? ([[t('imported'), batch.rows_imported]] as [string, number][]) : []),
    ...(includeImported ? [] : ([[t('valid'), batch.rows_valid]] as [string, number][])),
    [t('duplicates'), batch.rows_duplicate],
    [t('errors'), batch.rows_rejected],
    [t('unmapped'), batch.rows_unmapped],
    [t('review'), batch.rows_review],
  ];
  return (
    <section aria-label={label} className="border-line-soft bg-surface rounded-card border p-16">
      <dl className="grid grid-cols-2 gap-12 sm:grid-cols-3 lg:grid-cols-6">
        {items.map(([name, value]) => (
          <div key={name}>
            <dt className="text-label text-muted uppercase">{name}</dt>
            <dd className="text-kpi text-ink font-mono">{formatIndianNumber(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * The import wizard (blueprint 8 C3): upload, map columns, validate, preview, confirm, result. Everything the user
 * decides is saved on the batch, so `/imports/{id}` resumes at the right step. The API enforces every rule again.
 */
export function ImportWizard({ initialBatch }: { initialBatch?: ImportBatch }) {
  const t = useTranslations('imports');
  const router = useRouter();

  const [batch, setBatch] = useState<ImportBatch | null>(initialBatch ?? null);
  const [entity, setEntity] = useState<ImportEntity>('suppliers');
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<'idle' | 'uploading' | 'registering'>('idle');
  const [mapping, setMapping] = useState<Record<string, string>>(() => seedMapping(initialBatch));
  const [validating, setValidating] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [acceptPartial, setAcceptPartial] = useState(false);
  const [confirmKey, setConfirmKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Tone | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const pollStart = useRef(0);

  const step = stepOf(batch, validating, confirming);
  const polling = Boolean(
    batch &&
    !timedOut &&
    ((validating && batch.status === 'mapped') || batch.status === 'importing'),
  );
  const batchId = batch?.id;

  useEffect(() => {
    if (!polling || !batchId) return;
    pollStart.current = Date.now();
    const timer = setInterval(async () => {
      if (Date.now() - pollStart.current > POLL_LIMIT_MS) {
        setTimedOut(true);
        return;
      }
      try {
        setBatch(await apiGet<ImportBatch>(`/imports/${batchId}`));
      } catch {
        // A single failed poll is not an answer; the next tick asks again.
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, batchId]);

  const apiFailure = (e: unknown): Tone => ({
    kind: 'api',
    error: e instanceof ApiError ? e : new ApiError(0, null, null),
  });

  function stepNames(): Record<WizardStep, string> {
    return {
      upload: t('steps.upload'),
      map: t('steps.map'),
      validate: t('steps.validate'),
      preview: t('steps.preview'),
      confirm: t('steps.confirm'),
      result: t('steps.result'),
    };
  }

  function fieldLabel(entityName: string, field: string): string {
    const key = `fields.${entityName}.${field}`;
    return t.has(key) ? t(key) : field;
  }

  // ---- upload ------------------------------------------------------------------------------------------------
  async function upload() {
    if (!file) return;
    setFailure(null);
    const lower = file.name.toLowerCase();
    const contentType = lower.endsWith('.csv') ? 'text/csv' : lower.endsWith('.xlsx') ? XLSX : null;
    if (!contentType) {
      setFailure({
        kind: 'text',
        title: t('upload.wrongType.title'),
        detail: t('upload.wrongType.detail'),
      });
      return;
    }
    if (file.size === 0 || file.size > MAX_BYTES) {
      setFailure({ kind: 'text', title: t('upload.size.title'), detail: t('upload.size.detail') });
      return;
    }
    try {
      setStage('uploading');
      const target = await apiPost<{ key: string; url: string }>('/files/upload-url', {
        purpose: 'import',
        content_type: contentType,
        size: file.size,
      });
      let put: Response;
      try {
        put = await fetch(target.url, {
          method: 'PUT',
          body: file,
          headers: { 'Content-Type': contentType },
        });
      } catch {
        throw new Error('put');
      }
      if (!put.ok) throw new Error('put');

      setStage('registering');
      let created: ImportBatch | null = null;
      let last: unknown = null;
      for (let attempt = 0; attempt < SCAN_RETRIES && !created; attempt += 1) {
        try {
          created = await apiPost<ImportBatch>('/imports', {
            entity,
            key: target.key,
            file_name: file.name,
          });
        } catch (e) {
          last = e;
          // 404: the scan has not released the file yet. Anything else is a real answer.
          if (!(e instanceof ApiError) || e.status !== 404) throw e;
          await wait(SCAN_WAIT_MS);
        }
      }
      if (!created) {
        if (last instanceof ApiError && last.status === 404) {
          setFailure({
            kind: 'text',
            title: t('upload.scan.title'),
            detail: t('upload.scan.detail'),
          });
          return;
        }
        throw last;
      }
      // The create answer may be lean; the batch read model has the columns and the suggested mapping.
      const full = await apiGet<ImportBatch>(`/imports/${created.id}`);
      setBatch(full);
      setMapping(seedMapping(full));
    } catch (e) {
      if (e instanceof Error && e.message === 'put') {
        setFailure({ kind: 'text', title: t('upload.put.title'), detail: t('upload.put.detail') });
      } else {
        setFailure(apiFailure(e));
      }
    } finally {
      setStage('idle');
    }
  }

  // ---- map + validate ------------------------------------------------------------------------------------------
  async function validate() {
    if (!batch) return;
    setBusy(true);
    setFailure(null);
    try {
      const chosen = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
      await apiPost(`/imports/${batch.id}/map`, { mapping: chosen });
      await apiPost(`/imports/${batch.id}/validate`, {});
      setTimedOut(false);
      setValidating(true);
      setBatch(await apiGet<ImportBatch>(`/imports/${batch.id}`));
    } catch (e) {
      setFailure(apiFailure(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!batch) return;
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(`/imports/${batch.id}/cancel`, {});
      router.push('/imports');
    } catch (e) {
      setFailure(apiFailure(e));
      setBusy(false);
    }
  }

  // ---- confirm ----------------------------------------------------------------------------------------------------
  async function confirm() {
    if (!batch) return;
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(
        `/imports/${batch.id}/confirm`,
        { accept_partial: needsPartialConfirmation(batch) && acceptPartial },
        { idempotencyKey: confirmKey },
      );
      setTimedOut(false);
      setBatch(await apiGet<ImportBatch>(`/imports/${batch.id}`));
    } catch (e) {
      setConfirmKey(newIdempotencyKey()); // a changed request needs its own key
      setFailure(apiFailure(e));
    } finally {
      setBusy(false);
    }
  }

  const failureBlock = failure ? (
    failure.kind === 'api' ? (
      <ProblemAlert error={failure.error} />
    ) : (
      <Alert tone="error" title={failure.title}>
        {failure.detail}
      </Alert>
    )
  ) : null;

  const cancelButton =
    batch && ['uploaded', 'mapped', 'validated'].includes(batch.status) ? (
      <Button variant="ghost" onClick={cancel} disabled={busy}>
        {t('cancel')}
      </Button>
    ) : null;

  return (
    <>
      <ImportSteps label={t('steps.label')} names={stepNames()} current={step} />
      <div className="flex flex-col gap-16">
        {failureBlock}

        {step === 'upload' ? (
          <section aria-labelledby="step-heading" className="flex max-w-xl flex-col gap-16">
            <h2 id="step-heading" className="text-h2 text-ink">
              {t('upload.title')}
            </h2>
            <p className="text-body text-muted">{t('upload.intro')}</p>
            <SelectField
              label={t('upload.entity')}
              value={entity}
              onChange={(e) => setEntity(e.target.value as ImportEntity)}
              disabled={stage !== 'idle'}
            >
              {IMPORT_ENTITIES.map((x) => (
                <option key={x} value={x}>
                  {t(`entity.${x}`)}
                </option>
              ))}
            </SelectField>
            <div className="flex flex-col gap-4">
              <label htmlFor="import-file" className="text-h3 text-ink">
                {t('upload.file')}
              </label>
              <input
                id="import-file"
                type="file"
                accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                disabled={stage !== 'idle'}
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setFailure(null);
                }}
                className="border-line bg-surface text-body rounded-control min-h-target w-full border px-12 py-8"
              />
              <p className="text-caption text-muted">{t('upload.fileHelp')}</p>
              {file ? (
                <p className="text-body text-ink-2 break-all">
                  {t('upload.selected', { name: file.name })}
                </p>
              ) : null}
            </div>
            {stage !== 'idle' ? (
              <Progress
                label={stage === 'uploading' ? t('upload.sending') : t('upload.checking')}
              />
            ) : null}
            <div>
              <Button
                variant="primary"
                onClick={upload}
                disabled={!file || stage !== 'idle'}
                className="w-full sm:w-auto"
              >
                {t('upload.submit')}
              </Button>
            </div>
          </section>
        ) : null}

        {batch && step === 'map' ? (
          <section aria-labelledby="step-heading" className="flex max-w-xl flex-col gap-16">
            <h2 id="step-heading" className="text-h2 text-ink">
              {t('map.title')}
            </h2>
            {batch.file_hash_seen_before ? (
              <Alert
                tone="warning"
                title={t('map.seenBefore.title')}
                actions={
                  batch.previous_batch_ids[0] ? (
                    <Link
                      href={`/imports/${batch.previous_batch_ids[0]}`}
                      className={buttonClass('secondary')}
                    >
                      {t('map.seenBefore.link')}
                    </Link>
                  ) : null
                }
              >
                {t('map.seenBefore.detail')}
              </Alert>
            ) : null}
            <p className="text-body text-muted">{t('map.intro', { name: batch.file_name })}</p>
            {batch.target_fields.map((f) => (
              <SelectField
                key={f.name}
                label={fieldLabel(batch.entity, f.name)}
                requiredMark={f.required ? t('map.required') : undefined}
                required={f.required}
                value={mapping[f.name] ?? ''}
                onChange={(e) => setMapping((m) => ({ ...m, [f.name]: e.target.value }))}
              >
                <option value="">{t('map.notInFile')}</option>
                {batch.columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </SelectField>
            ))}
            {(() => {
              const missing = missingRequiredFields(batch.target_fields, mapping);
              return missing.length > 0 ? (
                <p className="text-caption text-muted">
                  {t('map.missing', {
                    fields: missing.map((m) => fieldLabel(batch.entity, m)).join(', '),
                  })}
                </p>
              ) : null;
            })()}
            <div className="flex flex-col-reverse gap-8 sm:flex-row">
              {cancelButton}
              <Button
                variant="primary"
                onClick={validate}
                disabled={busy || missingRequiredFields(batch.target_fields, mapping).length > 0}
              >
                {t('map.submit')}
              </Button>
            </div>
          </section>
        ) : null}

        {batch && step === 'validate' ? (
          <section aria-labelledby="step-heading" className="flex max-w-xl flex-col gap-16">
            <h2 id="step-heading" className="text-h2 text-ink">
              {t('validate.title')}
            </h2>
            {timedOut ? (
              <Alert tone="warning" title={t('slow.title')}>
                {t('slow.detail')}
              </Alert>
            ) : (
              <Progress label={t('validate.working')} />
            )}
            <div>{cancelButton}</div>
          </section>
        ) : null}

        {batch && step === 'preview' ? (
          <PreviewStep
            batch={batch}
            onContinue={() => setConfirming(true)}
            cancelButton={cancelButton}
          />
        ) : null}

        {batch && step === 'confirm' ? (
          <section aria-labelledby="step-heading" className="flex max-w-xl flex-col gap-16">
            <h2 id="step-heading" className="text-h2 text-ink">
              {t('confirm.title')}
            </h2>
            {batch.status === 'importing' ? (
              timedOut ? (
                <Alert tone="warning" title={t('slow.title')}>
                  {t('slow.detail')}
                </Alert>
              ) : (
                <Progress label={t('confirm.working')} />
              )
            ) : (
              <>
                <SummaryRegion batch={batch} label={t('summary.label')} includeImported={false} />
                {needsPartialConfirmation(batch) ? (
                  <>
                    <Alert tone="warning" title={t('confirm.partialTitle')}>
                      {t('confirm.partialDetail')}
                    </Alert>
                    <CheckboxField
                      label={t('confirm.accept', {
                        skipped: batch.rows_received - batch.rows_valid,
                      })}
                      checked={acceptPartial}
                      onChange={(e) => setAcceptPartial(e.target.checked)}
                    />
                  </>
                ) : (
                  <p className="text-body text-ink-2">
                    {t('confirm.clean', { count: batch.rows_valid })}
                  </p>
                )}
                <div className="flex flex-col-reverse gap-8 sm:flex-row">
                  {cancelButton}
                  <Button variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
                    {t('confirm.back')}
                  </Button>
                  <Button
                    variant="primary"
                    onClick={confirm}
                    disabled={busy || !canConfirm({ counts: batch, acceptPartial })}
                  >
                    {t('confirm.submit')}
                  </Button>
                </div>
              </>
            )}
          </section>
        ) : null}

        {batch && step === 'result' ? <ResultStep batch={batch} /> : null}
      </div>
    </>
  );
}

function seedMapping(batch: ImportBatch | undefined): Record<string, string> {
  if (!batch) return {};
  const base = Object.keys(batch.mapping).length > 0 ? batch.mapping : batch.suggested_mapping;
  // Only columns that exist in this file; a stale suggestion must not point at a missing column.
  return Object.fromEntries(
    Object.entries(base).filter(([, column]) => batch.columns.includes(column)),
  );
}

function PreviewStep({
  batch,
  onContinue,
  cancelButton,
}: {
  batch: ImportBatch;
  onContinue: () => void;
  cancelButton: React.ReactNode;
}) {
  const t = useTranslations('imports');
  const common = useTranslations('common');
  const counts: Record<string, number> = {
    errors: batch.rows_rejected,
    duplicates: batch.rows_duplicate,
    unmapped: batch.rows_unmapped,
    review: batch.rows_review,
    valid: batch.rows_valid,
  };
  const firstWithRows =
    ['errors', 'duplicates', 'unmapped', 'review'].find((k) => (counts[k] ?? 0) > 0) ?? 'valid';
  const [picked, setPicked] = useState<string | null>(null);
  const active = picked ?? firstWithRows;
  const rows = useKeyset<PreviewRow>(`/imports/${batch.id}/preview`, {
    status: TAB_STATUS[active],
  });

  const tabs = ['errors', 'duplicates', 'unmapped', 'review', 'valid'].map((id) => ({
    id,
    label: `${t(`preview.tabs.${id}`)} (${counts[id] ?? 0})`,
  }));

  const columns: Column<PreviewRow>[] = [
    { id: 'row', header: t('preview.columns.row'), cell: (r) => r.row_number, mono: true },
    {
      id: 'reason',
      header: t('preview.columns.reason'),
      cell: (r) => r.reason ?? t('preview.ready'),
    },
    {
      id: 'values',
      header: t('preview.columns.values'),
      hideOnPhone: true,
      cell: (r) =>
        Object.values(r.values ?? {})
          .filter(Boolean)
          .join(' · '),
    },
  ];

  return (
    <section aria-labelledby="step-heading" className="flex flex-col gap-16">
      <h2 id="step-heading" className="text-h2 text-ink">
        {t('preview.title')}
      </h2>
      <SummaryRegion batch={batch} label={t('summary.label')} includeImported={false} />
      <Tabs label={t('preview.tabsLabel')} tabs={tabs} active={active} onChange={setPicked}>
        {rows.error ? (
          <ProblemAlert
            error={rows.error}
            actions={<Button onClick={rows.reload}>{common('retry')}</Button>}
          />
        ) : rows.loading && rows.items.length === 0 ? (
          <Skeleton label={common('loading')} rows={3} />
        ) : rows.items.length === 0 ? (
          <EmptyState title={t('preview.empty')} />
        ) : (
          <>
            <DataTable
              label={t('preview.tableLabel')}
              columns={columns}
              rows={rows.items}
              rowKey={(r) => String(r.row_number)}
              dim={rows.loading}
            />
            {rows.hasMore ? (
              <div className="mt-16 flex justify-center">
                <Button onClick={rows.loadMore} disabled={rows.loadingMore}>
                  {common('loadMore')}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </Tabs>
      <div className="flex flex-col-reverse gap-8 sm:flex-row">
        {cancelButton}
        <Button variant="primary" onClick={onContinue} disabled={batch.rows_received === 0}>
          {t('preview.continue')}
        </Button>
      </div>
    </section>
  );
}

function ResultStep({ batch }: { batch: ImportBatch }) {
  const t = useTranslations('imports');
  if (batch.status === 'failed') {
    return (
      <section aria-labelledby="step-heading" className="flex flex-col gap-16">
        <h2 id="step-heading" className="text-h2 text-ink">
          {t('result.failedTitle')}
        </h2>
        <Alert tone="error" title={t('result.failedHeadline')}>
          {t('result.failedDetail')}
        </Alert>
        <div>
          <Link href="/imports/new" className={buttonClass('primary')}>
            {t('result.startAgain')}
          </Link>
        </div>
      </section>
    );
  }
  if (batch.status === 'cancelled') {
    return (
      <section aria-labelledby="step-heading" className="flex flex-col gap-16">
        <h2 id="step-heading" className="text-h2 text-ink">
          {t('result.cancelledTitle')}
        </h2>
        <Alert tone="info" role="status">
          {t('result.cancelledDetail')}
        </Alert>
        <div>
          <Link href="/imports/new" className={buttonClass('primary')}>
            {t('result.startAgain')}
          </Link>
        </div>
      </section>
    );
  }
  const target = batch.entity === 'suppliers' ? '/suppliers' : '/parts';
  return (
    <section aria-labelledby="step-heading" className="flex flex-col gap-16">
      <h2 id="step-heading" className="text-h2 text-ink">
        {t('result.title')}
      </h2>
      <SummaryRegion batch={batch} label={t('summary.label')} includeImported />
      {reconciles(batch) ? null : (
        <Alert tone="warning" title={t('result.mismatchTitle')}>
          {t('result.mismatchDetail')}
        </Alert>
      )}
      <div className="flex flex-col gap-8 sm:flex-row">
        <a
          href={`${API_BASE}/imports/${batch.id}/report.xlsx`}
          download
          className={buttonClass('primary')}
        >
          {t('result.download')}
        </a>
        <Link href={target} className={buttonClass('secondary')}>
          {batch.entity === 'suppliers' ? t('result.viewSuppliers') : t('result.viewParts')}
        </Link>
      </div>
    </section>
  );
}
