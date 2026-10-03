import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'destructive';

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    'border border-action bg-action text-surface hover:bg-action-hover hover:border-action-hover',
  secondary: 'border border-line bg-surface text-ink hover:bg-ground',
  ghost: 'border border-transparent bg-transparent text-action hover:bg-ground',
  destructive: 'border border-danger-mark bg-surface text-danger hover:bg-danger-bg',
};

const BASE =
  'text-h3 rounded-control min-h-target inline-flex items-center justify-center gap-8 px-16 py-8 text-center disabled:cursor-not-allowed disabled:border-line disabled:bg-line-soft disabled:text-muted';

export function buttonClass(variant: ButtonVariant = 'secondary', extra = ''): string {
  return `${BASE} ${VARIANT[variant]} ${extra}`.trim();
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  children: ReactNode;
};

/** One primary per view. Destructive buttons are never the default focus and ask for a reason (ReasonDialog). */
export function Button({ variant = 'secondary', type = 'button', className = '', ...rest }: Props) {
  return <button type={type} className={buttonClass(variant, className)} {...rest} />;
}
