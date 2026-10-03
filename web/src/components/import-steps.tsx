import { WIZARD_STEPS, type WizardStep } from '@/lib/import-wizard';

/**
 * The six steps in order. Each item holds only its name, so assistive technology reads "Map columns" and the current
 * one carries aria-current="step". Done / current / to-do differ by shape, not by colour alone.
 */
export function ImportSteps({
  label,
  names,
  current,
}: {
  label: string;
  names: Record<WizardStep, string>;
  current: WizardStep;
}) {
  const index = WIZARD_STEPS.indexOf(current);
  return (
    <ol aria-label={label} className="mb-24 grid grid-cols-2 gap-8 sm:grid-cols-6">
      {WIZARD_STEPS.map((step, i) => {
        const state = i < index ? 'done' : i === index ? 'current' : 'todo';
        return (
          <li
            key={step}
            aria-current={state === 'current' ? 'step' : undefined}
            className={`text-body rounded-control flex items-center gap-8 border px-12 py-8 ${
              state === 'current'
                ? 'border-action text-ink bg-surface'
                : state === 'done'
                  ? 'border-line-soft text-ink-2 bg-surface'
                  : 'border-line-soft text-muted bg-ground'
            }`}
          >
            <span
              aria-hidden="true"
              className={`size-12 shrink-0 rounded-pill ${
                state === 'done'
                  ? 'bg-ink-2'
                  : state === 'current'
                    ? 'bg-action'
                    : 'border-muted border-2'
              }`}
            />
            {names[step]}
          </li>
        );
      })}
    </ol>
  );
}
