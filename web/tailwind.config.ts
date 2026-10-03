import type { Config } from 'tailwindcss';

import {
  colors,
  fontFamilies,
  layout,
  radius,
  space,
  status,
  typography,
} from './src/design/tokens';

// The spec's 4 px scale, plus 0 so edge utilities (inset-x-0, bottom-0) exist.
const spacing = { '0': '0px', ...Object.fromEntries(space.map((s) => [String(s), `${s}px`])) };

const fontSize = Object.fromEntries(
  Object.entries(typography).map(([name, t]) => [
    name,
    [
      `${t.size}px`,
      {
        lineHeight: `${t.line}px`,
        fontWeight: String(t.weight),
        ...('letterSpacing' in t ? { letterSpacing: t.letterSpacing } : {}),
      },
    ],
  ]),
);

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    screens: {
      sm: `${layout.navBottomBarBreakpoint}px`,
      lg: `${layout.railBreakpoint}px`,
    },
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      ...colors,
      severity: Object.fromEntries(Object.entries(status.severity).map(([k, v]) => [k, v.bg])),
      // Message colours reuse the spec's status pairs: error = Critical, warning = Major, note = SCAR on time.
      danger: {
        DEFAULT: status.severity.critical.text,
        bg: status.severity.critical.bg,
        mark: status.severity.critical.mark,
      },
      caution: {
        DEFAULT: status.severity.major.text,
        bg: status.severity.major.bg,
        mark: status.severity.major.mark,
      },
      info: { DEFAULT: status.scarDue.onTime.text, bg: status.scarDue.onTime.bg },
    },
    spacing,
    borderRadius: {
      none: '0',
      control: `${radius.control}px`,
      card: `${radius.card}px`,
      pill: `${radius.pill}px`,
    },
    fontSize,
    fontFamily: {
      sans: [
        `var(--font-plex-sans)`,
        `var(--font-plex-devanagari)`,
        fontFamilies.sans,
        'sans-serif',
      ],
      mono: [`var(--font-plex-mono)`, fontFamilies.mono, 'monospace'],
    },
    extend: {
      width: { nav: `${layout.navWidth}px` },
      maxWidth: { content: `${layout.contentMax}px` },
      minHeight: {
        row: `${layout.tableRow}px`,
        'row-compact': `${layout.tableRowCompact}px`,
        target: `${layout.phoneTarget}px`,
      },
    },
  },
};

export default config;
