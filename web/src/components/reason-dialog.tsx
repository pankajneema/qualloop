'use client';

import { useId, useState, type ReactNode } from 'react';

import { Button } from '@/components/button';
import { Dialog } from '@/components/dialog';
import { isValidReason, REASON_MAX, reasonError } from '@/lib/reason';

export type ReasonDialogProps = {
  open: boolean;
  title: string;
  /** What will happen, in plain words (UX rule 8). */
  consequence: string;
  reasonLabel: string;
  /** Names the exact action, e.g. "Disable contact". */
  actionLabel: string;
  cancelLabel: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  /** Extra fields (for example the new status) shown above the reason. */
  children?: ReactNode;
  /** Keeps the confirm button disabled until the extra fields are complete. */
  extraInvalid?: boolean;
  busy?: boolean;
  /** An already translated error from the last attempt. */
  error?: ReactNode;
  destructive?: boolean;
  /** Translated "required" / "too long" texts for the inline reason error. */
  reasonErrors?: { required: string; too_long: string };
};

/**
 * Consequential actions ask why (UX rule 8): the dialog states the consequence, requires a reason of 1 to 2000
 * characters and names the exact action on its button. Text arrives translated, so it renders without next-intl.
 */
export function ReasonDialog(props: ReasonDialogProps) {
  // Mounted only while open, so the reason typed into a cancelled dialog never leaks into the next one.
  return props.open ? <ReasonDialogBody {...props} /> : null;
}

function ReasonDialogBody({
  open,
  title,
  consequence,
  reasonLabel,
  actionLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  children,
  extraInvalid = false,
  busy = false,
  error,
  destructive = false,
  reasonErrors,
}: ReasonDialogProps) {
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const fieldId = useId();
  const problem = reasonError(reason);
  const valid = isValidReason(reason);

  return (
    <Dialog
      open={open}
      title={title}
      description={consequence}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? 'destructive' : 'primary'}
            disabled={!valid || extraInvalid || busy}
            onClick={() => onConfirm(reason.trim())}
          >
            {actionLabel}
          </Button>
        </>
      }
    >
      {children}
      <div className="flex flex-col gap-4">
        <label htmlFor={fieldId} className="text-h3 text-ink">
          {reasonLabel}
        </label>
        <textarea
          id={fieldId}
          required
          maxLength={REASON_MAX}
          rows={3}
          value={reason}
          aria-invalid={touched && problem ? true : undefined}
          onChange={(event) => setReason(event.target.value)}
          onBlur={() => setTouched(true)}
          className="border-line bg-surface text-body text-ink rounded-control min-h-target w-full border px-12 py-8 aria-invalid:border-danger-mark"
        />
        <p className="text-caption text-muted font-mono">
          {reason.length}/{REASON_MAX}
        </p>
        {touched && problem && reasonErrors ? (
          <p className="text-caption text-danger">{reasonErrors[problem]}</p>
        ) : null}
      </div>
      {error}
    </Dialog>
  );
}
