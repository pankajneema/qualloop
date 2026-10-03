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

const spacing = Object.fromEntries(space.map((s) => [String(s), `${s}px`]));

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
