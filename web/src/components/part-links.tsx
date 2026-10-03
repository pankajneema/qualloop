'use client';

import Link from 'next/link';
import { useId, useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { DataTable, type Column } from '@/components/data-table';
import { Dialog } from '@/components/dialog';
import { SelectField, TextField } from '@/components/field';
import { ProblemAlert } from '@/components/problem-alert';
import { EmptyState, Skeleton } from '@/components/states';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import { formatIndianNumber } from '@/lib/format';
import type { Customer, CustomerPart, Page, Supplier, SupplierPart } from '@/lib/types';
import { useAsync } from '@/lib/use-async';

const PPM_MAX = 2147483647;

function asError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, null, null);
}

/** A strict positive integer up to 2147483647 (the API refuses anything else). */
function parsePpm(text: string): number | null {
  if (!/^[0-9]+$/.test(text.trim())) return null;
  const n = Number(text.trim());
  return n > 0 && n <= PPM_MAX ? n : null;
}

function Section({
  id,
  title,
  action,
  children,
}: {
  id: string;
  title: string;
  action: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="mt-32">
      <div className="mb-12 flex flex-wrap items-center justify-between gap-12">
        <h2 id={id} className="text-h2 text-ink">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Which suppliers make this part, with the PPM target of each link (blueprint 6.2, 14.4). */
export function SupplierLinks({ partId, canEdit }: { partId: string; canEdit: boolean }) {
  const t = useTranslations('parts.suppliers');
  const common = useTranslations('common');
  const data = useAsync<{ links: SupplierPart[]; names: Record<string, Supplier> }>(
    `supplier-links:${partId}`,
    async (signal) => {
      const page = await apiGet<Page<SupplierPart>>(
        '/supplier-parts',
        { part_id: partId, limit: 200 },
        signal,
      );
      const ids = [...new Set(page.items.map((l) => l.supplier_id))];
      const found = await Promise.all(
        ids.map((id) => apiGet<Supplier>(`/suppliers/${id}`, undefined, signal)),
      );
      return { links: page.items, names: Object.fromEntries(found.map((s) => [s.id, s])) };
    },
  );
  const [modal, setModal] = useState<
    { kind: 'link' } | { kind: 'edit' | 'unlink'; link: SupplierPart } | null
  >(null);

  const done = () => {
    setModal(null);
    data.reload();
  };

  const columns: Column<SupplierPart>[] = [
    {
      id: 'supplier',
      header: t('columns.supplier'),
      cell: (l) => {
        const s = data.data?.names[l.supplier_id];
        return s ? (
          <Link
            href={`/suppliers/${s.id}`}
            className="text-body min-h-target sm:min-h-row inline-flex items-center underline"
          >
            {s.name}
          </Link>
        ) : (
          l.supplier_id
        );
      },
    },
    {
      id: 'no',
      header: t('columns.supplierPartNo'),
      cell: (l) => l.supplier_part_no ?? '',
      mono: true,
      hideOnPhone: true,
    },
    {
      id: 'ppm',
      header: t('columns.ppmTarget'),
      cell: (l) => (l.ppm_target ? formatIndianNumber(l.ppm_target) : t('noTarget')),
      mono: true,
    },
  ];
  if (canEdit) {
    columns.push({
      id: 'actions',
      header: t('columns.actions'),
      cell: (l) => {
        const name = data.data?.names[l.supplier_id]?.name ?? '';
        return (
          <div className="flex flex-wrap gap-4">
            <Button
              variant="ghost"
              aria-label={`${t('edit')} ${name}`}
              onClick={() => setModal({ kind: 'edit', link: l })}
            >
              {t('edit')}
            </Button>
            <Button
              variant="ghost"
              aria-label={`${t('unlink')} ${name}`}
              onClick={() => setModal({ kind: 'unlink', link: l })}
            >
              {t('unlink')}
            </Button>
          </div>
        );
      },
    });
  }

  return (
    <Section
      id="supplier-links-heading"
      title={t('title')}
      action={
        canEdit ? <Button onClick={() => setModal({ kind: 'link' })}>{t('link')}</Button> : null
      }
    >
      {data.error ? (
        <ProblemAlert
          error={data.error}
          actions={<Button onClick={data.reload}>{common('retry')}</Button>}
        />
      ) : !data.data ? (
        <Skeleton label={common('loading')} rows={2} />
      ) : data.data.links.length === 0 ? (
        <EmptyState title={t('empty.title')}>{t('empty.body')}</EmptyState>
      ) : (
        <DataTable
          label={t('tableLabel')}
          columns={columns}
          rows={data.data.links}
          rowKey={(l) => l.id}
        />
      )}
      {modal?.kind === 'link' ? (
        <LinkSupplierDialog partId={partId} onClose={() => setModal(null)} onSaved={done} />
      ) : null}
      {modal?.kind === 'edit' ? (
        <EditLinkDialog
          link={modal.link}
          name={data.data?.names[modal.link.supplier_id]?.name ?? ''}
          onClose={() => setModal(null)}
          onSaved={done}
        />
      ) : null}
      {modal?.kind === 'unlink' ? (
        <UnlinkDialog
          path={`/supplier-parts/${modal.link.id}/archive`}
          title={t('unlinkDialog.title')}
          body={t('unlinkDialog.body', {
            name: data.data?.names[modal.link.supplier_id]?.name ?? '',
          })}
          action={t('unlink')}
          onClose={() => setModal(null)}
          onSaved={done}
        />
      ) : null}
    </Section>
  );
}

function LinkSupplierDialog({
  partId,
  onClose,
  onSaved,
}: {
  partId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('parts.suppliers.linkDialog');
  const common = useTranslations('common');
  const formId = useId();
  const [search, setSearch] = useState('');
  const [found, setFound] = useState<Supplier[] | null>(null);
  const [supplierId, setSupplierId] = useState('');
  const [no, setNo] = useState('');
  const [ppm, setPpm] = useState('');
  const [errors, setErrors] = useState<{ supplier?: string; ppm?: string }>({});
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function lookup() {
    setFailure(null);
    try {
      const page = await apiGet<Page<Supplier>>('/suppliers', { q: search.trim(), limit: 20 });
      setFound(page.items);
      setSupplierId(page.items[0]?.id ?? '');
    } catch (e) {
      setFailure(asError(e));
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const next: { supplier?: string; ppm?: string } = {};
    if (!supplierId) next.supplier = t('errors.supplier');
    const target = ppm.trim() ? parsePpm(ppm) : null;
    if (ppm.trim() && target === null) next.ppm = t('errors.ppm');
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    setBusy(true);
    setFailure(null);
    try {
      await apiPost('/supplier-parts', {
        supplier_id: supplierId,
        part_id: partId,
        ...(no.trim() ? { supplier_part_no: no.trim() } : {}),
        ...(target !== null ? { ppm_target: target } : {}),
      });
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
      title={t('title')}
      description={t('intro')}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {common('cancel')}
          </Button>
          <Button type="submit" form={formId} variant="primary" disabled={busy}>
            {t('submit')}
          </Button>
        </>
      }
    >
      {failure ? <ProblemAlert error={failure} /> : null}
      <div className="flex items-end gap-8">
        <div className="flex-1">
          <TextField
            label={t('search')}
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void lookup();
              }
            }}
          />
        </div>
        <Button onClick={() => void lookup()}>{t('find')}</Button>
      </div>
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-16">
        <SelectField
          label={t('supplier')}
          value={supplierId}
          error={errors.supplier}
          onChange={(e) => setSupplierId(e.target.value)}
          help={found && found.length === 0 ? t('noResults') : undefined}
        >
          <option value="">{t('choose')}</option>
          {(found ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.code})
            </option>
          ))}
        </SelectField>
        <TextField
          label={t('supplierPartNo')}
          value={no}
          onChange={(e) => setNo(e.target.value)}
          className="font-mono"
        />
        <TextField
          label={t('ppmTarget')}
          inputMode="numeric"
          help={t('ppmHelp')}
          value={ppm}
          error={errors.ppm}
          onChange={(e) => setPpm(e.target.value)}
          className="font-mono"
        />
      </form>
    </Dialog>
  );
}

function EditLinkDialog({
  link,
  name,
  onClose,
  onSaved,
}: {
  link: SupplierPart;
  name: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('parts.suppliers.editDialog');
  const common = useTranslations('common');
  const formId = useId();
  const [no, setNo] = useState(link.supplier_part_no ?? '');
  const [ppm, setPpm] = useState(link.ppm_target ? String(link.ppm_target) : '');
  const [error, setError] = useState<string | undefined>();
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const target = ppm.trim() ? parsePpm(ppm) : null;
    if (ppm.trim() && target === null) {
      setError(t('ppmError'));
      return;
    }
    setError(undefined);
    setBusy(true);
    setFailure(null);
    try {
      const body: Record<string, string | number | null> = {};
      if (no.trim() !== (link.supplier_part_no ?? '')) body.supplier_part_no = no.trim() || null;
      if (target !== link.ppm_target) body.ppm_target = target;
      if (Object.keys(body).length > 0) await apiPost(`/supplier-parts/${link.id}/update`, body);
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
      title={t('title', { name })}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {common('cancel')}
          </Button>
          <Button type="submit" form={formId} variant="primary" disabled={busy}>
            {t('submit')}
          </Button>
        </>
      }
    >
      {failure ? <ProblemAlert error={failure} /> : null}
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-16">
        <TextField
          label={t('supplierPartNo')}
          value={no}
          onChange={(e) => setNo(e.target.value)}
          className="font-mono"
        />
        <TextField
          label={t('ppmTarget')}
          inputMode="numeric"
          help={t('ppmHelp')}
          value={ppm}
          error={error}
          onChange={(e) => setPpm(e.target.value)}
          className="font-mono"
        />
      </form>
    </Dialog>
  );
}

function UnlinkDialog({
  path,
  title,
  body,
  action,
  onClose,
  onSaved,
}: {
  path: string;
  title: string;
  body: string;
  action: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const common = useTranslations('common');
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setFailure(null);
    try {
      await apiPost(path, {});
      onSaved();
    } catch (e) {
      setFailure(asError(e));
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      title={title}
      description={body}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {common('cancel')}
          </Button>
          <Button variant="destructive" onClick={() => void run()} disabled={busy}>
            {action}
          </Button>
        </>
      }
    >
      {failure ? <ProblemAlert error={failure} /> : null}
    </Dialog>
  );
}

/** Which customers use this part (many-to-many, INV-MST-01). */
export function CustomerLinks({ partId, canEdit }: { partId: string; canEdit: boolean }) {
  const t = useTranslations('parts.customers');
  const common = useTranslations('common');
  const data = useAsync<{ links: CustomerPart[]; customers: Customer[] }>(
    `customer-links:${partId}`,
    async (signal) => {
      const [links, customers] = await Promise.all([
        apiGet<Page<CustomerPart>>('/customer-parts', { part_id: partId, limit: 200 }, signal),
        apiGet<Page<Customer>>('/customers', { limit: 200 }, signal),
      ]);
      return { links: links.items, customers: customers.items };
    },
  );
  const [modal, setModal] = useState<
    { kind: 'link' } | { kind: 'unlink'; link: CustomerPart } | null
  >(null);
  const nameOf = (id: string) => data.data?.customers.find((c) => c.id === id)?.name ?? '';
  const done = () => {
    setModal(null);
    data.reload();
  };

  const columns: Column<CustomerPart>[] = [
    {
      id: 'customer',
      header: t('columns.customer'),
      cell: (l) => nameOf(l.customer_id) || l.customer_id,
    },
    {
      id: 'no',
      header: t('columns.customerPartNo'),
      cell: (l) => l.customer_part_no ?? '',
      mono: true,
    },
  ];
  if (canEdit) {
    columns.push({
      id: 'actions',
      header: t('columns.actions'),
      cell: (l) => (
        <Button
          variant="ghost"
          aria-label={`${t('unlink')} ${nameOf(l.customer_id)}`}
          onClick={() => setModal({ kind: 'unlink', link: l })}
        >
          {t('unlink')}
        </Button>
      ),
    });
  }

  return (
    <Section
      id="customer-links-heading"
      title={t('title')}
      action={
        canEdit ? <Button onClick={() => setModal({ kind: 'link' })}>{t('link')}</Button> : null
      }
    >
      {data.error ? (
        <ProblemAlert
          error={data.error}
          actions={<Button onClick={data.reload}>{common('retry')}</Button>}
        />
      ) : !data.data ? (
        <Skeleton label={common('loading')} rows={2} />
      ) : data.data.links.length === 0 ? (
        <EmptyState title={t('empty.title')}>{t('empty.body')}</EmptyState>
      ) : (
        <DataTable
          label={t('tableLabel')}
          columns={columns}
          rows={data.data.links}
          rowKey={(l) => l.id}
        />
      )}
      {modal?.kind === 'link' && data.data ? (
        <LinkCustomerDialog
          partId={partId}
          customers={data.data.customers}
          onClose={() => setModal(null)}
          onSaved={done}
        />
      ) : null}
      {modal?.kind === 'unlink' ? (
        <UnlinkDialog
          path={`/customer-parts/${modal.link.id}/archive`}
          title={t('unlinkDialog.title')}
          body={t('unlinkDialog.body', { name: nameOf(modal.link.customer_id) })}
          action={t('unlink')}
          onClose={() => setModal(null)}
          onSaved={done}
        />
      ) : null}
    </Section>
  );
}

const NEW_CUSTOMER = '__new__';

function LinkCustomerDialog({
  partId,
  customers,
  onClose,
  onSaved,
}: {
  partId: string;
  customers: Customer[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('parts.customers.linkDialog');
  const common = useTranslations('common');
  const formId = useId();
  const [customerId, setCustomerId] = useState('');
  const [newName, setNewName] = useState('');
  const [newCode, setNewCode] = useState('');
  const [no, setNo] = useState('');
  const [errors, setErrors] = useState<{ customer?: string; name?: string; code?: string }>({});
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const creating = customerId === NEW_CUSTOMER;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const next: { customer?: string; name?: string; code?: string } = {};
    if (!customerId) next.customer = t('errors.customer');
    if (creating && !newName.trim()) next.name = t('errors.name');
    if (creating && !newCode.trim()) next.code = t('errors.code');
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    setBusy(true);
    setFailure(null);
    try {
      let id = customerId;
      if (creating) {
        const created = await apiPost<Customer>('/customers', {
          name: newName.trim(),
          code: newCode.trim(),
        });
        id = created.id;
      }
      await apiPost('/customer-parts', {
        customer_id: id,
        part_id: partId,
        ...(no.trim() ? { customer_part_no: no.trim() } : {}),
      });
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
      title={t('title')}
      description={t('intro')}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {common('cancel')}
          </Button>
          <Button type="submit" form={formId} variant="primary" disabled={busy}>
            {t('submit')}
          </Button>
        </>
      }
    >
      {failure ? <ProblemAlert error={failure} /> : null}
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-16">
        <SelectField
          label={t('customer')}
          value={customerId}
          error={errors.customer}
          onChange={(e) => setCustomerId(e.target.value)}
        >
          <option value="">{t('choose')}</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.code})
            </option>
          ))}
          <option value={NEW_CUSTOMER}>{t('newCustomer')}</option>
        </SelectField>
        {creating ? (
          <>
            <TextField
              label={t('newName')}
              value={newName}
              error={errors.name}
              onChange={(e) => setNewName(e.target.value)}
            />
            <TextField
              label={t('newCode')}
              value={newCode}
              error={errors.code}
              onChange={(e) => setNewCode(e.target.value)}
              className="font-mono"
            />
          </>
        ) : null}
        <TextField
          label={t('customerPartNo')}
          value={no}
          onChange={(e) => setNo(e.target.value)}
          className="font-mono"
        />
      </form>
    </Dialog>
  );
}
