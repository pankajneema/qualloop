/**
 * Design tokens. Every value comes from docs/design/DESIGN_SPEC.md; nothing here is invented.
 * Tailwind's theme (tailwind.config.ts) and the CSS variables (cssVariables) are generated from this file.
 * Hex literals are forbidden anywhere else (eslint no-restricted-syntax).
 */

export const fontFamilies = {
  sans: 'IBM Plex Sans',
  devanagari: 'IBM Plex Sans Devanagari',
  mono: 'IBM Plex Mono',
} as const;

type TypeToken = {
  size: number;
  line: number;
  weight: number;
  mono?: true;
  uppercase?: true;
  letterSpacing?: string;
};

/** px sizes. Devanagari text adds `devanagariLineHeightExtra` px to line-height. */
export const typography = {
  display: { size: 32, line: 40, weight: 600 },
  h1: { size: 24, line: 32, weight: 600 },
  h2: { size: 18, line: 26, weight: 600 },
  h3: { size: 15, line: 22, weight: 600 },
  body: { size: 14, line: 20, weight: 400 },
  'body-mobile': { size: 16, line: 24, weight: 400 },
  caption: { size: 12, line: 16, weight: 500 },
  label: { size: 11, line: 16, weight: 600, uppercase: true, letterSpacing: '0.06em' },
  kpi: { size: 28, line: 32, weight: 500, mono: true },
  data: { size: 13, line: 20, weight: 400, mono: true },
} as const satisfies Record<string, TypeToken>;

export const devanagariLineHeightExtra = 2;

export const colors = {
  ink: '#101828',
  'ink-2': '#344054',
  muted: '#475467',
  subtle: '#667085',
  line: '#D0D5DD',
  'line-soft': '#E4E7EC',
  ground: '#F5F6F8',
  surface: '#FFFFFF',
  action: '#1D4ED8',
  'action-hover': '#1E3A8A',
} as const;

type Pair = { bg: string; text: string };

export const status = {
  severity: {
    critical: { bg: '#FEE4E2', text: '#912018', mark: '#B42318', shape: 'square' },
    major: { bg: '#FEF0C7', text: '#93370D', mark: '#DC6803', shape: 'circle' },
    minor: { bg: '#F2F4F7', text: '#344054', shape: 'hollow-circle' },
  },
  scarDue: {
    onTime: { bg: '#D1E9FF', text: '#194185' },
    late: { bg: '#FEF0C7', text: '#93370D' },
    overdue: { bg: '#B42318', text: '#FFFFFF' }, // solid, shows days
    notYetDue: { bg: '#F2F4F7', text: '#344054' },
  },
  certificateValidity: {
    // SPEC-GAP Q-D1: spec names the colour family ("blue", "amber") without hex; reuse the spec's
    // blue pair (SCAR on-time) and amber pair (Major / Late). Confirm at the next human gate.
    valid: { bg: '#D1E9FF', text: '#194185' },
    expiring: { bg: '#FEF0C7', text: '#93370D' },
    expired: { bg: '#FEE4E2', text: '#912018' },
    exception: { bg: '#F4EBFF', text: '#53389E' },
    // "Not requested": dashed outline, no fill colour defined by the spec.
  },
  risk: {
    // SPEC-GAP Q-D1: "Low grey" / "Medium amber" have no hex; reuse the spec's grey and amber pairs.
    low: { bg: '#F2F4F7', text: '#344054' },
    medium: { bg: '#FEF0C7', text: '#93370D' },
    high: { bg: '#912018', text: '#FFFFFF' }, // solid, shows score and trend arrow
  },
  aiSuggestion: { bg: '#F4F3FF', border: '#D9D6FE', label: 'Suggestion · not applied' },
} as const satisfies Record<string, Record<string, Pair | object | string>>;

/** 4 px base. */
export const space = [4, 8, 12, 16, 24, 32, 48] as const;

export const radius = { control: 6, card: 8, pill: 999 } as const;

export const layout = {
  navWidth: 232,
  contentMax: 1360,
  /** Below this the context rail drops below the work area. */
  railBreakpoint: 1024,
  /** Below this the nav becomes a bottom bar. */
  navBottomBarBreakpoint: 640,
  tableRow: 40,
  tableRowCompact: 32,
  phoneTarget: 48,
} as const;

const px = (n: number): string => `${n}px`;

/** CSS custom properties (applied on <html>), so CSS never repeats a token value. */
export const cssVariables: Record<string, string> = {
  ...Object.fromEntries(Object.entries(colors).map(([k, v]) => [`--ql-color-${k}`, v])),
  '--ql-nav-width': px(layout.navWidth),
  '--ql-content-max': px(layout.contentMax),
  '--ql-radius-control': px(radius.control),
  '--ql-radius-card': px(radius.card),
  '--ql-radius-pill': px(radius.pill),
  '--ql-devanagari-extra-line': px(devanagariLineHeightExtra),
  ...Object.fromEntries(space.map((s) => [`--ql-space-${s}`, px(s)])),
};
