import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { colors, layout, radius, space, status, typography } from './tokens';

const spec = readFileSync(join(__dirname, '../../../docs/design/DESIGN_SPEC.md'), 'utf8');

describe('tokens match docs/design/DESIGN_SPEC.md', () => {
  it('colour table', () => {
    const rows = [
      ...spec.matchAll(/^\| ([a-z0-9-]+) \| (#[0-9A-F]{6})(?: \(hover (#[0-9A-F]{6})\))? \|/gm),
    ];
    expect(rows.length).toBe(9);
    for (const [, name, hex, hover] of rows) {
      expect(colors[name as keyof typeof colors], name).toBe(hex);
      if (hover) expect(colors['action-hover']).toBe(hover);
    }
  });

  it('typography table', () => {
    const rows = [...spec.matchAll(/^\| ([a-z0-9-]+) \| (\d+) \/ (\d+) \/ (\d+)/gm)];
    expect(rows.map((r) => r[1])).toEqual(Object.keys(typography));
    for (const [, name, size, line, weight] of rows) {
      const t = typography[name as keyof typeof typography];
      expect([t.size, t.line, t.weight], name).toEqual([
        Number(size),
        Number(line),
        Number(weight),
      ]);
    }
    expect(typography.label.letterSpacing).toBe('0.06em');
    expect('mono' in typography.kpi && 'mono' in typography.data).toBe(true);
  });

  it('status colours', () => {
    expect(status.severity.critical).toMatchObject({
      bg: '#FEE4E2',
      text: '#912018',
      mark: '#B42318',
    });
    expect(status.severity.major).toMatchObject({
      bg: '#FEF0C7',
      text: '#93370D',
      mark: '#DC6803',
    });
    expect(status.severity.minor).toMatchObject({ bg: '#F2F4F7', text: '#344054' });
    expect(status.scarDue.onTime).toEqual({ bg: '#D1E9FF', text: '#194185' });
    expect(status.scarDue.late).toEqual({ bg: '#FEF0C7', text: '#93370D' });
    expect(status.scarDue.overdue.bg).toBe('#B42318');
    expect(status.scarDue.notYetDue).toEqual({ bg: '#F2F4F7', text: '#344054' });
    expect(status.certificateValidity.expired).toEqual({ bg: '#FEE4E2', text: '#912018' });
    expect(status.certificateValidity.exception).toEqual({ bg: '#F4EBFF', text: '#53389E' });
    expect(status.risk.high.bg).toBe('#912018');
    expect(status.aiSuggestion).toMatchObject({ bg: '#F4F3FF', border: '#D9D6FE' });
    expect(status.aiSuggestion.label).toBe('Suggestion · not applied');
  });

  it('space, radius, layout', () => {
    expect([...space]).toEqual([4, 8, 12, 16, 24, 32, 48]);
    expect(radius).toEqual({ control: 6, card: 8, pill: 999 });
    expect(layout).toMatchObject({
      navWidth: 232,
      contentMax: 1360,
      railBreakpoint: 1024,
      navBottomBarBreakpoint: 640,
      tableRow: 40,
      tableRowCompact: 32,
      phoneTarget: 48,
    });
  });
});
