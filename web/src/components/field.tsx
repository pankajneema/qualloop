import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

const CONTROL =
  'border-line bg-surface text-body text-ink rounded-control min-h-target w-full border px-12 py-8 aria-invalid:border-danger-mark disabled:bg-ground disabled:text-muted';

type Common = {
  label: string;
  help?: string;
  error?: string;
  /** Marks the field as required for assistive technology; shown as a mark outside the label text. */
  requiredMark?: string;
};

function Wrapper({
  id,
  label,
  help,
  error,
  requiredMark,
  children,
}: Common & { id: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline gap-4">
        <label htmlFor={id} className="text-h3 text-ink">
          {label}
        </label>
        {requiredMark ? (
          <span className="text-caption text-muted" aria-hidden="true">
            {requiredMark}
          </span>
        ) : null}
      </div>
      {error ? (
        <p id={`${id}-error`} className="text-caption text-danger">
          {error}
        </p>
      ) : null}
      {children}
      {help ? (
        <p id={`${id}-help`} className="text-caption text-muted">
          {help}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, help?: string, error?: string): string | undefined {
  const ids = [help ? `${id}-help` : '', error ? `${id}-error` : ''].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

export function TextField({
  label,
  help,
  error,
  requiredMark,
  className = '',
  ...rest
}: Common & Omit<InputHTMLAttributes<HTMLInputElement>, 'id'>) {
  const id = useId();
  return (
    <Wrapper id={id} label={label} help={help} error={error} requiredMark={requiredMark}>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, help, error)}
        className={`${CONTROL} ${className}`}
        {...rest}
      />
    </Wrapper>
  );
}

export function TextAreaField({
  label,
  help,
  error,
  requiredMark,
  className = '',
  ...rest
}: Common & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'>) {
  const id = useId();
  return (
    <Wrapper id={id} label={label} help={help} error={error} requiredMark={requiredMark}>
      <textarea
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, help, error)}
        className={`${CONTROL} ${className}`}
        {...rest}
      />
    </Wrapper>
  );
}

export function SelectField({
  label,
  help,
  error,
  requiredMark,
  className = '',
  children,
  ...rest
}: Common & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'>) {
  const id = useId();
  return (
    <Wrapper id={id} label={label} help={help} error={error} requiredMark={requiredMark}>
      <select
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, help, error)}
        className={`${CONTROL} ${className}`}
        {...rest}
      >
        {children}
      </select>
    </Wrapper>
  );
}

export function CheckboxField({
  label,
  className = '',
  ...rest
}: { label: string } & Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'type'>) {
  const id = useId();
  return (
    <div className={`flex items-start gap-12 ${className}`}>
      <input id={id} type="checkbox" className="size-24 mt-4 shrink-0" {...rest} />
      <label htmlFor={id} className="text-body text-ink-2 min-h-target flex items-center">
        {label}
      </label>
    </div>
  );
}
