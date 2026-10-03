'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type DialogProps = {
  open: boolean;
  title: string;
  /** Text under the title (the consequence, for a ReasonDialog). */
  description?: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
};

/** Modal dialog: labelled by its title, traps Tab, closes on Escape, returns focus to what opened it. */
export function Dialog(props: DialogProps) {
  if (!props.open) return null;
  return <DialogPanel {...props} />;
}

function DialogPanel({ title, description, onClose, children, footer }: DialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = panel.current;
    // First field first; the confirm button is never the initial focus.
    const field = node?.querySelector<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
    );
    (field ?? node)?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, []);

  return (
    <div className="bg-ink/40 fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-16">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className="bg-surface border-line-soft max-h-screen w-full max-w-lg overflow-y-auto rounded-t-card border p-16 shadow-lg sm:rounded-card sm:p-24"
      >
        <h2 id={titleId} className="text-h2 text-ink">
          {title}
        </h2>
        {description ? (
          <p id={descriptionId} className="text-body text-ink-2 mt-8">
            {description}
          </p>
        ) : null}
        <div className="mt-16 flex flex-col gap-16">{children}</div>
        <div className="mt-24 flex flex-col-reverse gap-8 sm:flex-row sm:justify-end">{footer}</div>
      </div>
    </div>
  );
}
