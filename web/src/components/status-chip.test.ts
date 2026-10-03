import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type StatusChipProps = {
  kind: 'supplier-status';
  value: 'approved' | 'approved_with_action_plan' | 'on_watch' | 'blocked' | 'inactive';
  label: string;
};
type Chip = { StatusChip: (props: StatusChipProps) => React.ReactElement };

const STATUSES: [StatusChipProps['value'], string][] = [
  ['approved', 'Approved'],
  ['approved_with_action_plan', 'Approved with action plan'],
  ['on_watch', 'On watch'],
  ['blocked', 'Blocked'],
  ['inactive', 'Inactive'],
];

async function render(value: StatusChipProps['value'], label: string): Promise<string> {
  const { StatusChip } = await load<Chip>('@/components/status-chip');
  return renderToStaticMarkup(createElement(StatusChip, { kind: 'supplier-status', value, label }));
}

describe('StatusChip for supplier status (DESIGN_SPEC: outlined chips only, UX rule 6)', () => {
  it.each(STATUSES)(
    '%s renders as an outlined chip that says its status in words',
    async (value, label) => {
      const html = await render(value, label);
      expect(html).toContain('data-testid="status-chip"');
      expect(html).toContain('data-variant="outlined"');
      expect(html).toContain(`data-status="${value}"`);
      expect(html).toContain(label);
    },
  );

  it('never uses a filled or risk variant', async () => {
    for (const [value, label] of STATUSES) {
      const html = await render(value, label);
      expect(html).not.toMatch(/data-variant="(filled|solid|risk)/);
      expect(html).not.toMatch(/risk/i);
    }
  });

  it('is not shape or colour alone: the word is in the text content', async () => {
    const html = await render('blocked', 'Blocked');
    expect(html.replace(/<[^>]+>/g, '').trim()).toBe('Blocked');
  });

  it('escapes its label', async () => {
    const html = await render('approved', '<img src=x onerror=alert(1)>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });
});
