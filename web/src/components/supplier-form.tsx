'use client';

import { useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { SelectField, TextField } from '@/components/field';
import { ProblemAlert } from '@/components/problem-alert';
import { ApiError } from '@/lib/api';
import { useHydrated } from '@/lib/use-hydrated';
import { useDescribe } from '@/lib/use-problem';
import {
  SUPPLIER_CATEGORIES,
  SUPPLIER_STATUSES,
  type Supplier,
  type SupplierCategory,
  type SupplierStatus,
} from '@/lib/types';

export type SupplierFormValues = {
  code: string;
  name: string;
  gstin: string;
  city: string;
  state: string;
  category: '' | SupplierCategory;
  status: '' | SupplierStatus;
};

type FieldName = keyof SupplierFormValues;

// Same pattern the API enforces (INV: gstin matches ^[0-9A-Z]{15}$); checked here only to explain it early.
const GSTIN = /^[0-9A-Z]{15}$/;

export function valuesFromSupplier(s: Supplier): SupplierFormValues {
  return {
    code: s.code,
    name: s.name,
    gstin: s.gstin ?? '',
    city: s.city ?? '',
    state: s.state ?? '',
    category: s.category,
    status: s.status,
  };
}

export const EMPTY_SUPPLIER: SupplierFormValues = {
  code: '',
  name: '',
  gstin: '',
  city: '',
  state: '',
  category: '',
  status: '',
};

/**
 * Create and edit share this form. On create the status is required (A-06); without can_approve only "Approved" is
 * offered (A-116, the API refuses anything else). On edit there is no status field: status changes go only through the
 * Change status dialog (INV-MST-03).
 */
export function SupplierForm({
  mode,
  initial,
  canChooseStatus,
  submitLabel,
  onSubmit,
}: {
  mode: 'create' | 'edit';
  initial: SupplierFormValues;
  canChooseStatus: boolean;
  submitLabel: string;
  onSubmit: (values: SupplierFormValues) => Promise<void>;
}) {
  const t = useTranslations('suppliers.form');
  const status = useTranslations('suppliers.status');
  const category = useTranslations('suppliers.category');
  const describe = useDescribe();
  const [values, setValues] = useState<SupplierFormValues>(initial);
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({});
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const hydrated = useHydrated();

  const set = (name: FieldName) => (value: string) => setValues((v) => ({ ...v, [name]: value }));

  function validate(): Partial<Record<FieldName, string>> {
    const found: Partial<Record<FieldName, string>> = {};
    if (!values.code.trim()) found.code = t('errors.code');
    if (!values.name.trim()) found.name = t('errors.name');
    const gstin = values.gstin.trim().toUpperCase();
    if (gstin && !GSTIN.test(gstin)) found.gstin = t('errors.gstin');
    if (!values.category) found.category = t('errors.category');
    if (mode === 'create' && !values.status) found.status = t('errors.status');
    return found;
  }

  function focusFirstInvalid() {
    setTimeout(() => document.querySelector<HTMLElement>('form [aria-invalid="true"]')?.focus(), 0);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) {
      focusFirstInvalid();
      return;
    }
    setBusy(true);
    try {
      await onSubmit({ ...values, gstin: values.gstin.trim().toUpperCase() });
    } catch (e) {
      const error = e instanceof ApiError ? e : new ApiError(0, null, null);
      const fields = describe(error).fields;
      const mapped: Partial<Record<FieldName, string>> = {};
      for (const name of [
        'code',
        'name',
        'gstin',
        'city',
        'state',
        'category',
        'status',
      ] as const) {
        if (fields[name]) mapped[name] = fields[name];
      }
      setErrors(mapped);
      setFailure(error);
      focusFirstInvalid();
    } finally {
      setBusy(false);
    }
  }

  const required = t('required');
  return (
    <form onSubmit={submit} noValidate className="flex max-w-xl flex-col gap-16">
      {failure ? <ProblemAlert error={failure} /> : null}
      <TextField
        label={t('code')}
        requiredMark={required}
        required
        value={values.code}
        error={errors.code}
        onChange={(e) => set('code')(e.target.value)}
      />
      <TextField
        label={t('name')}
        requiredMark={required}
        required
        value={values.name}
        error={errors.name}
        onChange={(e) => set('name')(e.target.value)}
      />
      <TextField
        label={t('gstin')}
        help={t('gstinHelp')}
        value={values.gstin}
        error={errors.gstin}
        maxLength={15}
        autoCapitalize="characters"
        onChange={(e) => set('gstin')(e.target.value.toUpperCase())}
        className="font-mono"
      />
      <div className="grid gap-16 sm:grid-cols-2">
        <TextField
          label={t('city')}
          value={values.city}
          error={errors.city}
          onChange={(e) => set('city')(e.target.value)}
        />
        <TextField
          label={t('state')}
          value={values.state}
          error={errors.state}
          onChange={(e) => set('state')(e.target.value)}
        />
      </div>
      <SelectField
        label={t('category')}
        requiredMark={required}
        required
        value={values.category}
        error={errors.category}
        onChange={(e) => set('category')(e.target.value)}
      >
        <option value="">{t('categoryPlaceholder')}</option>
        {SUPPLIER_CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {category(c)}
          </option>
        ))}
      </SelectField>
      {mode === 'create' ? (
        <SelectField
          label={t('status')}
          requiredMark={required}
          required
          help={canChooseStatus ? undefined : t('statusHelpLimited')}
          value={values.status}
          error={errors.status}
          onChange={(e) => set('status')(e.target.value)}
        >
          <option value="">{t('statusPlaceholder')}</option>
          {SUPPLIER_STATUSES.filter((s) => canChooseStatus || s === 'approved').map((s) => (
            <option key={s} value={s}>
              {status(s)}
            </option>
          ))}
        </SelectField>
      ) : null}
      <div className="sm:flex sm:justify-start">
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !hydrated}
          className="w-full sm:w-auto"
        >
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
