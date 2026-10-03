/** Import wizard rules (blueprint 8 C3, INV-IMP-06). The API enforces every one of them again. */

export const WIZARD_STEPS = ['upload', 'map', 'validate', 'preview', 'confirm', 'result'] as const;
export type WizardStep = (typeof WIZARD_STEPS)[number];

export type Counts = {
  rows_received: number;
  rows_valid: number;
  rows_imported: number;
  rows_duplicate: number;
  rows_rejected: number;
  rows_unmapped: number;
  rows_review: number;
};

export type TargetField = { name: string; required: boolean };

/** Anything that is not a valid row makes the import partial and needs the explicit tick. */
export function needsPartialConfirmation(counts: Counts): boolean {
  return (
    counts.rows_duplicate + counts.rows_rejected + counts.rows_unmapped + counts.rows_review > 0
  );
}

export function canConfirm(input: { counts: Counts; acceptPartial: boolean }): boolean {
  if (input.counts.rows_received <= 0) return false;
  return !needsPartialConfirmation(input.counts) || input.acceptPartial;
}

export function missingRequiredFields(
  targetFields: TargetField[],
  mapping: Record<string, string>,
): string[] {
  return targetFields
    .filter((f) => f.required && !(mapping[f.name] ?? '').trim())
    .map((f) => f.name);
}

/** After completion every received row is in exactly one bucket. */
export function reconciles(counts: Counts): boolean {
  return (
    counts.rows_imported +
      counts.rows_duplicate +
      counts.rows_rejected +
      counts.rows_unmapped +
      counts.rows_review ===
    counts.rows_received
  );
}
