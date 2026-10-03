'use client';

import { useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/button';
import { TextField } from '@/components/field';
import { ProblemAlert } from '@/components/problem-alert';
import { ApiError } from '@/lib/api';
import { useHydrated } from '@/lib/use-hydrated';
import { useDescribe } from '@/lib/use-problem';

export type PartValues = {
  part_no: string;
  name: string;
  category: string;
  current_revision: string;
};

/** Part number is fixed once the part exists (the API's update takes name, category and revision only). */
export function PartForm({
  mode,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  mode: 'create' | 'edit';
  initial: PartValues;
  submitLabel: string;
  onSubmit: (values: PartValues) => Promise<void>;
  onCancel?: () => void;
}) {
  const t = useTranslations('parts.form');
  const common = useTranslations('common');
  const describe = useDescribe();
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState<Partial<Record<keyof PartValues, string>>>({});
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const hydrated = useHydrated();
  const set = (name: keyof PartValues) => (value: string) =>
    setValues((v) => ({ ...v, [name]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found: Partial<Record<keyof PartValues, string>> = {};
    if (mode === 'create' && !values.part_no.trim()) found.part_no = t('errors.partNo');
    if (!values.name.trim()) found.name = t('errors.name');
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) {
      setTimeout(
        () => document.querySelector<HTMLElement>('form [aria-invalid="true"]')?.focus(),
        0,
      );
      return;
    }
    setBusy(true);
    try {
      await onSubmit(values);
    } catch (e) {
      const error = e instanceof ApiError ? e : new ApiError(0, null, null);
      const fields = describe(error).fields;
      const mapped: Partial<Record<keyof PartValues, string>> = {};
      for (const name of ['part_no', 'name', 'category', 'current_revision'] as const) {
        if (fields[name]) mapped[name] = fields[name];
      }
      setErrors(mapped);
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex max-w-xl flex-col gap-16">
      {failure ? <ProblemAlert error={failure} /> : null}
      {mode === 'create' ? (
        <TextField
          label={t('partNo')}
          requiredMark={t('required')}
          required
          value={values.part_no}
          error={errors.part_no}
          className="font-mono"
          onChange={(e) => set('part_no')(e.target.value)}
        />
      ) : null}
      <TextField
        label={t('name')}
        requiredMark={t('required')}
        required
        value={values.name}
        error={errors.name}
        onChange={(e) => set('name')(e.target.value)}
      />
      <TextField
        label={t('category')}
        value={values.category}
        error={errors.category}
        onChange={(e) => set('category')(e.target.value)}
      />
      <TextField
        label={t('revision')}
        value={values.current_revision}
        error={errors.current_revision}
        className="font-mono"
        onChange={(e) => set('current_revision')(e.target.value)}
      />
      <div className="flex flex-col-reverse gap-8 sm:flex-row">
        {onCancel ? <Button onClick={onCancel}>{common('cancel')}</Button> : null}
        <Button type="submit" variant="primary" disabled={busy || !hydrated}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
