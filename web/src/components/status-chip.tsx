import type { SupplierStatus } from '@/lib/types';

/** Shapes carry meaning next to the word, so status is never colour alone (DESIGN_SPEC). Each is an empty element. */
const SHAPE: Record<SupplierStatus, string> = {
  approved: 'size-8 rounded-pill bg-ink-2',
  approved_with_action_plan: 'size-8 rotate-45 bg-ink-2',
  on_watch: 'size-8 rounded-pill border-2 border-ink-2',
  blocked: 'size-8 bg-ink',
  inactive: 'size-8 rounded-pill border-2 border-dashed border-muted',
};

export type StatusChipProps = {
  kind: 'supplier-status';
  value: SupplierStatus;
  label: string;
};

/**
 * Supplier status is a human decision, so it is an outlined, transparent chip with the word inside. It never shares
 * a style with the system's signals (UX rule 6). The label arrives translated; React escapes it.
 */
export function StatusChip({ value, label }: StatusChipProps) {
  return (
    <span
      data-testid="status-chip"
      data-variant="outlined"
      data-status={value}
      className="text-caption text-ink-2 inline-flex items-center gap-8 rounded-pill border border-ink-2 bg-transparent px-12 py-4 whitespace-nowrap"
    >
      <span aria-hidden="true" className={SHAPE[value] ?? SHAPE.inactive} />
      {label}
    </span>
  );
}
