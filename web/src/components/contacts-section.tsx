'use client';

import { useId, useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { DataTable, type Column } from '@/components/data-table';
import { Dialog } from '@/components/dialog';
import { SelectField, TextField } from '@/components/field';
import { ProblemAlert } from '@/components/problem-alert';
import { ReasonDialog } from '@/components/reason-dialog';
import { Alert, Badge, EmptyState, Skeleton } from '@/components/states';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import type { ConsentChannel, ConsentStatus, Contact, Page } from '@/lib/types';
import { useAsync } from '@/lib/use-async';
import { useFormatDate } from '@/lib/use-format';

// Same shape the API enforces for mobile numbers (E.164); checked here only to explain it before sending.
const E164 = /^\+[1-9][0-9]{7,14}$/;
const CHANNELS: ConsentChannel[] = ['whatsapp', 'email', 'sms'];

type Modal =
  | { kind: 'add' }
  | { kind: 'edit' | 'verify' | 'consents' | 'replace' | 'disable'; id: string }
  | null;

function asError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, null, null);
}

/** Contacts of one supplier (blueprint 8 C2): add, edit, verify by OTP, quality contact, consents, replace, disable. */
export function ContactsSection({ supplierId, canEdit }: { supplierId: string; canEdit: boolean }) {
  const t = useTranslations('contacts');
  const common = useTranslations('common');
  const formatDate = useFormatDate();
  const contacts = useAsync<Contact[]>(`contacts:${supplierId}`, async (signal) => {
    const page = await apiGet<Page<Contact> | Contact[]>(
      `/suppliers/${supplierId}/contacts`,
      { limit: 200 },
      signal,
    );
    return Array.isArray(page) ? page : page.items;
  });
  const [modal, setModal] = useState<Modal>(null);
  const [rowError, setRowError] = useState<ApiError | null>(null);

  const list = contacts.data ?? [];
  const target = modal && modal.kind !== 'add' ? list.find((c) => c.id === modal.id) : undefined;

  function done() {
    setModal(null);
    contacts.reload();
  }

  async function makeQuality(contact: Contact) {
    setRowError(null);
    try {
      await apiPost(`/contacts/${contact.id}/set-quality-contact`, {});
      contacts.reload();
    } catch (e) {
      setRowError(asError(e));
    }
  }

  const action = (key: string, name: string) => `${t(`actions.${key}`)} ${name}`;

  const columns: Column<Contact>[] = [
    {
      id: 'contact',
      header: t('columns.contact'),
      cell: (c) => (
        <div className={c.active ? '' : 'text-muted'}>
          <p className="text-h3 text-ink">{c.name}</p>
          {c.role ? <p className="text-caption text-muted">{c.role}</p> : null}
          {c.mobile ? (
            <p className="text-data font-mono">
              {c.mobile}
              {c.verified_mobile_at ? (
                <span className="text-caption text-muted font-sans">
                  {' '}
                  · {t('verifiedOn', { date: formatDate(c.verified_mobile_at) })}
                </span>
              ) : null}
            </p>
          ) : null}
          {c.email ? (
            <p className="text-data font-mono break-all">
              {c.email}
              {c.verified_email_at ? (
                <span className="text-caption text-muted font-sans">
                  {' '}
                  · {t('verifiedOn', { date: formatDate(c.verified_email_at) })}
                </span>
              ) : null}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      id: 'status',
      header: t('columns.status'),
      cell: (c) => (
        <div className="flex flex-wrap gap-4">
          {c.is_quality_contact ? <Badge>{t('badges.quality')}</Badge> : null}
          {c.active && c.needs_reverification ? (
            <Badge tone="warning">{t('badges.needsVerification')}</Badge>
          ) : null}
          {!c.active ? <Badge>{t('badges.disabled')}</Badge> : null}
          {c.replaced_by_contact_id ? <Badge>{t('badges.replaced')}</Badge> : null}
        </div>
      ),
    },
  ];
  if (canEdit) {
    columns.push({
      id: 'actions',
      header: t('columns.actions'),
      cell: (c) =>
        c.active ? (
          <div className="flex flex-wrap gap-4">
            <Button
              variant="ghost"
              aria-label={action('edit', c.name)}
              onClick={() => setModal({ kind: 'edit', id: c.id })}
            >
              {t('actions.edit')}
            </Button>
            <Button
              variant="ghost"
              aria-label={action('verify', c.name)}
              onClick={() => setModal({ kind: 'verify', id: c.id })}
            >
              {t('actions.verify')}
            </Button>
            {c.is_quality_contact ? null : (
              <Button
                variant="ghost"
                aria-label={action('makeQuality', c.name)}
                onClick={() => makeQuality(c)}
              >
                {t('actions.makeQuality')}
              </Button>
            )}
            <Button
              variant="ghost"
              aria-label={action('consents', c.name)}
              onClick={() => setModal({ kind: 'consents', id: c.id })}
            >
              {t('actions.consents')}
            </Button>
            <Button
              variant="ghost"
              aria-label={action('replace', c.name)}
              onClick={() => setModal({ kind: 'replace', id: c.id })}
            >
              {t('actions.replace')}
            </Button>
            <Button
              variant="ghost"
              aria-label={action('disable', c.name)}
              onClick={() => setModal({ kind: 'disable', id: c.id })}
            >
              {t('actions.disable')}
            </Button>
          </div>
        ) : null,
    });
  }

  return (
    <section aria-labelledby="contacts-heading" className="mt-32">
      <div className="mb-12 flex flex-wrap items-center justify-between gap-12">
        <h2 id="contacts-heading" className="text-h2 text-ink">
          {t('title')}
        </h2>
        {canEdit ? (
          <Button onClick={() => setModal({ kind: 'add' })}>{t('add.title')}</Button>
        ) : null}
      </div>
      {rowError ? (
        <div className="mb-12">
          <ProblemAlert error={rowError} />
        </div>
      ) : null}
      {contacts.error ? (
        <ProblemAlert
          error={contacts.error}
          actions={<Button onClick={contacts.reload}>{common('retry')}</Button>}
        />
      ) : !contacts.data ? (
        <Skeleton label={common('loading')} rows={3} />
      ) : list.length === 0 ? (
        <EmptyState title={t('empty.title')}>
          {canEdit ? t('empty.body') : t('empty.viewerBody')}
        </EmptyState>
      ) : (
        <DataTable label={t('tableLabel')} columns={columns} rows={list} rowKey={(c) => c.id} />
      )}

      {modal?.kind === 'add' ? (
        <ContactFormDialog supplierId={supplierId} onClose={() => setModal(null)} onSaved={done} />
      ) : null}
      {modal?.kind === 'edit' && target ? (
        <ContactFormDialog
          supplierId={supplierId}
          contact={target}
          onClose={() => setModal(null)}
          onSaved={done}
        />
      ) : null}
      {modal?.kind === 'verify' && target ? (
        <VerifyDialog
          contact={target}
          onClose={() => setModal(null)}
          onVerified={contacts.reload}
        />
      ) : null}
      {modal?.kind === 'consents' && target ? (
        <ConsentsDialog
          contact={target}
          onClose={() => setModal(null)}
          onChanged={contacts.reload}
        />
      ) : null}
      {modal?.kind === 'replace' && target ? (
        <ReplaceDialog contact={target} onClose={() => setModal(null)} onSaved={done} />
      ) : null}
      {modal?.kind === 'disable' && target ? (
        <DisableDialog contact={target} onClose={() => setModal(null)} onSaved={done} />
      ) : null}
    </section>
  );
}

type ContactValues = { name: string; role: string; mobile: string; email: string };

function ContactFields({
  values,
  errors,
  onChange,
}: {
  values: ContactValues;
  errors: Partial<Record<keyof ContactValues | 'contact', string>>;
  onChange: (name: keyof ContactValues, value: string) => void;
}) {
  const t = useTranslations('contacts.form');
  return (
    <>
      <TextField
        label={t('name')}
        required
        value={values.name}
        error={errors.name}
        onChange={(e) => onChange('name', e.target.value)}
      />
      <TextField
        label={t('role')}
        value={values.role}
        onChange={(e) => onChange('role', e.target.value)}
      />
      <TextField
        label={t('mobile')}
        type="tel"
        inputMode="tel"
        autoComplete="off"
        help={t('mobileHelp')}
        value={values.mobile}
        error={errors.mobile ?? errors.contact}
        onChange={(e) => onChange('mobile', e.target.value)}
      />
      <TextField
        label={t('email')}
        type="email"
        autoComplete="off"
        value={values.email}
        error={errors.email}
        onChange={(e) => onChange('email', e.target.value)}
      />
    </>
  );
}

function validateContact(values: ContactValues, t: (key: string) => string) {
  const errors: Partial<Record<keyof ContactValues | 'contact', string>> = {};
  if (!values.name.trim()) errors.name = t('errors.name');
  const mobile = values.mobile.trim();
  const email = values.email.trim();
  if (!mobile && !email) errors.contact = t('errors.contact');
  else if (mobile && !E164.test(mobile)) errors.mobile = t('errors.mobile');
  return errors;
}

function ContactFormDialog({
  supplierId,
  contact,
  onClose,
  onSaved,
}: {
  supplierId: string;
  contact?: Contact;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('contacts');
  const common = useTranslations('common');
  const formId = useId();
  const [values, setValues] = useState<ContactValues>({
    name: contact?.name ?? '',
    role: contact?.role ?? '',
    mobile: contact?.mobile ?? '',
    email: contact?.email ?? '',
  });
  const [errors, setErrors] = useState<Partial<Record<keyof ContactValues | 'contact', string>>>(
    {},
  );
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const title = contact ? t('edit.title') : t('add.title');

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validateContact(values, (k) => t(`form.${k}`));
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) {
      setTimeout(
        () => document.querySelector<HTMLElement>('[role="dialog"] [aria-invalid="true"]')?.focus(),
        0,
      );
      return;
    }
    setBusy(true);
    try {
      const name = values.name.trim();
      const role = values.role.trim();
      const mobile = values.mobile.trim();
      const email = values.email.trim();
      if (contact) {
        // Only what changed; null clears a value (API: changing a number clears its verification).
        const body: Record<string, string | null> = {};
        if (name !== contact.name) body.name = name;
        if (role !== (contact.role ?? '')) body.role = role || null;
        if (mobile !== (contact.mobile ?? '')) body.mobile = mobile || null;
        if (email !== (contact.email ?? '')) body.email = email || null;
        if (Object.keys(body).length > 0) await apiPost(`/contacts/${contact.id}/update`, body);
      } else {
        await apiPost(`/suppliers/${supplierId}/contacts`, {
          name,
          ...(role ? { role } : {}),
          ...(mobile ? { mobile } : {}),
          ...(email ? { email } : {}),
        });
      }
      onSaved();
    } catch (e) {
      setFailure(asError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      title={title}
      description={contact ? t('edit.consequence') : t('add.intro')}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {common('cancel')}
          </Button>
          <Button type="submit" form={formId} variant="primary" disabled={busy}>
            {contact ? t('edit.submit') : t('add.submit')}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-16">
        {failure ? <ProblemAlert error={failure} /> : null}
        <ContactFields
          values={values}
          errors={errors}
          onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
        />
      </form>
    </Dialog>
  );
}

function VerifyDialog({
  contact,
  onClose,
  onVerified,
}: {
  contact: Contact;
  onClose: () => void;
  onVerified: () => void;
}) {
  const t = useTranslations('contacts.verify');
  const common = useTranslations('common');
  const channels = (['mobile', 'email'] as const).filter((c) =>
    c === 'mobile' ? contact.mobile : contact.email,
  );
  const [channel, setChannel] = useState<'mobile' | 'email'>(channels[0] ?? 'mobile');
  const [stage, setStage] = useState<'choose' | 'enter' | 'done'>('choose');
  const [code, setCode] = useState('');
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(`/contacts/${contact.id}/verify/start`, { channel });
      setStage('enter');
    } catch (e) {
      setFailure(asError(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(`/contacts/${contact.id}/verify/confirm`, { channel, code: code.trim() });
      setStage('done');
      onVerified();
    } catch (e) {
      setFailure(asError(e));
    } finally {
      setBusy(false);
    }
  }

  const footer =
    stage === 'done' ? (
      <Button variant="primary" onClick={onClose}>
        {common('close')}
      </Button>
    ) : (
      <>
        <Button onClick={onClose} disabled={busy}>
          {common('cancel')}
        </Button>
        {stage === 'choose' ? (
          <Button variant="primary" onClick={start} disabled={busy || channels.length === 0}>
            {t('send')}
          </Button>
        ) : (
          <Button
            type="submit"
            form="verify-form"
            variant="primary"
            disabled={busy || code.trim().length !== 6}
          >
            {t('confirm')}
          </Button>
        )}
      </>
    );

  return (
    <Dialog
      open
      title={t('title', { name: contact.name })}
      description={stage === 'enter' ? t('enterIntro') : t('chooseIntro')}
      onClose={onClose}
      footer={footer}
    >
      {failure ? <ProblemAlert error={failure} /> : null}
      {stage === 'choose' ? (
        channels.length === 0 ? (
          <Alert tone="warning">{t('noDestination')}</Alert>
        ) : (
          <SelectField
            label={t('channel')}
            value={channel}
            onChange={(e) => setChannel(e.target.value as 'mobile' | 'email')}
          >
            {channels.map((c) => (
              <option key={c} value={c}>
                {c === 'mobile'
                  ? t('viaMobile', { to: contact.mobile ?? '' })
                  : t('viaEmail', { to: contact.email ?? '' })}
              </option>
            ))}
          </SelectField>
        )
      ) : null}
      {stage === 'enter' ? (
        <form id="verify-form" onSubmit={confirm} noValidate>
          <TextField
            label={t('code')}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="font-mono"
          />
        </form>
      ) : null}
      {stage === 'done' ? (
        <Alert tone="info" role="status" title={t('doneTitle')}>
          {t('doneDetail')}
        </Alert>
      ) : null}
    </Dialog>
  );
}

function consentState(contact: Contact, channel: ConsentChannel): ConsentStatus | null {
  const rows = contact.consents.filter((c) => c.channel === channel);
  if (rows.some((c) => c.status === 'opted_in')) return 'opted_in';
  if (rows.some((c) => c.status === 'opted_out')) return 'opted_out';
  return null;
}

function ConsentsDialog({
  contact,
  onClose,
  onChanged,
}: {
  contact: Contact;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations('contacts.consents');
  const common = useTranslations('common');
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function record(channel: ConsentChannel, status: ConsentStatus) {
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(`/contacts/${contact.id}/consents`, { channel, status, source: 'manual' });
      onChanged();
    } catch (e) {
      setFailure(asError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      title={t('title', { name: contact.name })}
      description={t('intro')}
      onClose={onClose}
      footer={
        <Button variant="primary" onClick={onClose}>
          {common('close')}
        </Button>
      }
    >
      {failure ? <ProblemAlert error={failure} /> : null}
      <ul className="flex flex-col gap-12">
        {CHANNELS.map((channel) => {
          const state = consentState(contact, channel);
          return (
            <li
              key={channel}
              className="border-line-soft rounded-card flex flex-wrap items-center justify-between gap-8 border p-12"
            >
              <div>
                <p className="text-h3 text-ink">{t(`channel.${channel}`)}</p>
                <p className="text-caption text-muted">
                  {state ? t(`state.${state}`) : t('state.none')}
                </p>
              </div>
              <div className="flex flex-wrap gap-8">
                <Button
                  disabled={busy || state === 'opted_in'}
                  onClick={() => record(channel, 'opted_in')}
                >
                  {t('optIn')}
                </Button>
                <Button
                  disabled={busy || state === 'opted_out'}
                  onClick={() => record(channel, 'opted_out')}
                >
                  {t('optOut')}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}

function ReplaceDialog({
  contact,
  onClose,
  onSaved,
}: {
  contact: Contact;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('contacts');
  const common = useTranslations('common');
  const reasonT = useTranslations('common.reason');
  const [values, setValues] = useState<ContactValues>({
    name: '',
    role: '',
    mobile: '',
    email: '',
  });
  const [errors, setErrors] = useState<Partial<Record<keyof ContactValues | 'contact', string>>>(
    {},
  );
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function replace(reason: string) {
    const found = validateContact(values, (k) => t(`form.${k}`));
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    try {
      const role = values.role.trim();
      const mobile = values.mobile.trim();
      const email = values.email.trim();
      await apiPost(`/contacts/${contact.id}/replace`, {
        reason,
        name: values.name.trim(),
        ...(role ? { role } : {}),
        ...(mobile ? { mobile } : {}),
        ...(email ? { email } : {}),
      });
      onSaved();
    } catch (e) {
      setFailure(asError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ReasonDialog
      open
      title={t('replace.title', { name: contact.name })}
      consequence={t('replace.consequence', { name: contact.name })}
      reasonLabel={t('replace.reason')}
      actionLabel={t('replace.action')}
      cancelLabel={common('cancel')}
      busy={busy}
      error={failure ? <ProblemAlert error={failure} /> : null}
      reasonErrors={{ required: reasonT('required'), too_long: reasonT('tooLong') }}
      extraInvalid={!values.name.trim()}
      onCancel={onClose}
      onConfirm={replace}
    >
      <ContactFields
        values={values}
        errors={errors}
        onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
      />
    </ReasonDialog>
  );
}

function DisableDialog({
  contact,
  onClose,
  onSaved,
}: {
  contact: Contact;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('contacts');
  const common = useTranslations('common');
  const reasonT = useTranslations('common.reason');
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function disable(reason: string) {
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(`/contacts/${contact.id}/disable`, { reason });
      onSaved();
    } catch (e) {
      setFailure(asError(e));
      setBusy(false);
    }
  }

  return (
    <ReasonDialog
      open
      title={t('disable.title')}
      consequence={t('disable.consequence', { name: contact.name })}
      reasonLabel={t('disable.reason')}
      actionLabel={t('disable.title')}
      cancelLabel={common('cancel')}
      busy={busy}
      destructive
      error={failure ? <ProblemAlert error={failure} /> : null}
      reasonErrors={{ required: reasonT('required'), too_long: reasonT('tooLong') }}
      onCancel={onClose}
      onConfirm={disable}
    />
  );
}
