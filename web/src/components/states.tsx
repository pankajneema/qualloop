import type { ReactNode } from 'react';

type Tone = 'error' | 'warning' | 'info';

const TONE: Record<Tone, { box: string; mark: string }> = {
  error: { box: 'border-danger-mark bg-danger-bg text-danger', mark: 'bg-danger-mark' },
  warning: {
    box: 'border-caution-mark bg-caution-bg text-caution',
    mark: 'bg-caution-mark rounded-pill',
  },
  info: { box: 'border-info bg-info-bg text-info', mark: 'bg-info rotate-45' },
};

/** Messages pair a shape with the words, so they never rely on colour alone. */
export function Alert({
  tone,
  title,
  children,
  role,
  actions,
}: {
  tone: Tone;
  title?: string;
  children?: ReactNode;
  role?: 'alert' | 'status';
  actions?: ReactNode;
}) {
  const style = TONE[tone];
  return (
    <div
      role={role ?? (tone === 'info' ? 'status' : 'alert')}
      className={`rounded-card flex gap-12 border p-16 ${style.box}`}
    >
      <span aria-hidden="true" className={`size-12 mt-4 shrink-0 ${style.mark}`} />
      <div className="text-body min-w-0 flex-1 break-words">
        {title ? <p className="text-h3">{title}</p> : null}
        {children ? <div className={title ? 'mt-4' : ''}>{children}</div> : null}
        {actions ? <div className="mt-8 flex flex-wrap gap-8">{actions}</div> : null}
      </div>
    </div>
  );
}

/** Placeholder blocks while data loads. The status text is for screen readers. */
export function Skeleton({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-busy="true" className="flex flex-col gap-8">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="bg-line-soft rounded-control h-row animate-pulse"
        />
      ))}
    </div>
  );
}

/** An empty list teaches what to do next (UX rule: empty states teach). */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="border-line bg-surface rounded-card flex flex-col items-start gap-8 border border-dashed p-24">
      <p className="text-h3 text-ink">{title}</p>
      {children ? <div className="text-body text-muted">{children}</div> : null}
      {action}
    </div>
  );
}

/** A small labelled marker (not a status chip): shape plus the words. */
export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'warning';
  children: ReactNode;
}) {
  const warning = tone === 'warning';
  return (
    <span
      className={`text-caption inline-flex items-center gap-4 rounded-pill border px-8 py-4 whitespace-nowrap ${
        warning
          ? 'border-caution-mark bg-caution-bg text-caution'
          : 'border-line text-ink-2 bg-surface'
      }`}
    >
      <span
        aria-hidden="true"
        className={`size-8 ${warning ? 'bg-caution-mark rounded-pill' : 'border-ink-2 border'}`}
      />
      {children}
    </span>
  );
}
