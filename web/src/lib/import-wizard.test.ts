import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type Counts = {
  rows_received: number;
  rows_valid: number;
  rows_imported: number;
  rows_duplicate: number;
  rows_rejected: number;
  rows_unmapped: number;
  rows_review: number;
};
type Field = { name: string; required: boolean };
type Wizard = {
  WIZARD_STEPS: readonly string[];
  needsPartialConfirmation(counts: Counts): boolean;
  canConfirm(input: { counts: Counts; acceptPartial: boolean }): boolean;
  missingRequiredFields(fields: Field[], mapping: Record<string, string>): string[];
  reconciles(counts: Counts): boolean;
};
const wizard = () => load<Wizard>('@/lib/import-wizard');

const counts = (over: Partial<Counts> = {}): Counts => ({
  rows_received: 0,
  rows_valid: 0,
  rows_imported: 0,
  rows_duplicate: 0,
  rows_rejected: 0,
  rows_unmapped: 0,
  rows_review: 0,
  ...over,
});

describe('import wizard rules (blueprint 8 C3, INV-IMP-06)', () => {
  it('walks the six documented steps in order', async () => {
    expect((await wizard()).WIZARD_STEPS).toEqual([
      'upload',
      'map',
      'validate',
      'preview',
      'confirm',
      'result',
    ]);
  });

  it('a batch with only valid rows needs no partial confirmation and can be confirmed', async () => {
    const { needsPartialConfirmation, canConfirm } = await wizard();
    const clean = counts({ rows_received: 4, rows_valid: 4 });
    expect(needsPartialConfirmation(clean)).toBe(false);
    expect(canConfirm({ counts: clean, acceptPartial: false })).toBe(true);
  });

  it.each([
    ['duplicate', { rows_duplicate: 1 }],
    ['rejected', { rows_rejected: 1 }],
    ['unmapped', { rows_unmapped: 1 }],
    ['review', { rows_review: 1 }],
  ])('a single %s row makes the import partial', async (_name, over) => {
    const { needsPartialConfirmation } = await wizard();
    expect(needsPartialConfirmation(counts({ rows_received: 4, rows_valid: 3, ...over }))).toBe(
      true,
    );
  });

  it('a partial import cannot be confirmed until the user accepts it', async () => {
    const { canConfirm } = await wizard();
    const partial = counts({ rows_received: 4, rows_valid: 3, rows_rejected: 1 });
    expect(canConfirm({ counts: partial, acceptPartial: false })).toBe(false);
    expect(canConfirm({ counts: partial, acceptPartial: true })).toBe(true);
  });

  it('a batch with no rows at all cannot be confirmed', async () => {
    const { canConfirm } = await wizard();
    expect(canConfirm({ counts: counts(), acceptPartial: true })).toBe(false);
  });

  it('lists the required fields that are not mapped yet', async () => {
    const { missingRequiredFields } = await wizard();
    const fields: Field[] = [
      { name: 'code', required: true },
      { name: 'name', required: true },
      { name: 'gstin', required: false },
    ];
    expect(missingRequiredFields(fields, {})).toEqual(['code', 'name']);
    expect(missingRequiredFields(fields, { code: 'Supplier Code' })).toEqual(['name']);
    expect(missingRequiredFields(fields, { code: 'A', name: 'B' })).toEqual([]);
    expect(missingRequiredFields(fields, { code: '', name: 'B' })).toEqual(['code']);
  });

  it('checks that the counts reconcile to the rows received', async () => {
    const { reconciles } = await wizard();
    expect(
      reconciles(
        counts({
          rows_received: 7,
          rows_imported: 3,
          rows_duplicate: 2,
          rows_rejected: 1,
          rows_review: 1,
        }),
      ),
    ).toBe(true);
    expect(reconciles(counts({ rows_received: 7, rows_imported: 3 }))).toBe(false);
  });
});
