'use client';

import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react';

export type TabItem = { id: string; label: string };

/** Tabs with one visible panel; arrow keys move between tabs (WAI-ARIA tabs pattern). */
export function Tabs({
  label,
  tabs,
  active,
  onChange,
  children,
}: {
  label: string;
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  children: ReactNode;
}) {
  const base = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: KeyboardEvent, index: number) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    const edge = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (!step && edge === null) return;
    event.preventDefault();
    const next = edge ?? (index + step + tabs.length) % tabs.length;
    const target = tabs[next];
    if (!target) return;
    onChange(target.id);
    refs.current[target.id]?.focus();
  }

  return (
    <div>
      <div role="tablist" aria-label={label} className="border-line flex flex-wrap gap-4 border-b">
        {tabs.map((tab, index) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                refs.current[tab.id] = node;
              }}
              type="button"
              role="tab"
              id={`${base}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${base}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={`text-h3 min-h-target px-16 py-8 border-b-2 ${
                selected ? 'border-action text-ink' : 'text-muted hover:text-ink border-transparent'
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${base}-panel`}
        aria-labelledby={`${base}-tab-${active}`}
        tabIndex={0}
        className="pt-16"
      >
        {children}
      </div>
    </div>
  );
}
