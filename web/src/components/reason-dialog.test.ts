import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type ReasonDialogProps = {
  open: boolean;
  title: string;
  consequence: string;
  reasonLabel: string;
  actionLabel: string;
  cancelLabel: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
};
type Dialog = { ReasonDialog: (props: ReasonDialogProps) => React.ReactElement | null };

const props: ReasonDialogProps = {
  open: true,
  title: 'Block supplier',
  consequence:
    'Blocked suppliers cannot receive new orders until a Head of Quality changes the status.',
  reasonLabel: 'Reason',
  actionLabel: 'Block supplier',
  cancelLabel: 'Keep current status',
  onConfirm: () => undefined,
  onCancel: () => undefined,
};

async function render(over: Partial<ReasonDialogProps> = {}): Promise<string> {
  const { ReasonDialog } = await load<Dialog>('@/components/reason-dialog');
  return renderToStaticMarkup(createElement(ReasonDialog, { ...props, ...over }));
}

describe('ReasonDialog (DESIGN_SPEC: states the consequence, requires a reason, names the exact action)', () => {
  it('is an accessible modal dialog named by its title', async () => {
    const html = await render();
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    const id = /aria-labelledby="([^"]+)"/.exec(html)?.[1] ?? '';
    expect(id).not.toBe('');
    expect(html).toMatch(new RegExp(`id="${id}"[^>]*>Block supplier<`));
  });

  it('states the consequence', async () => {
    expect(await render()).toContain(props.consequence);
  });

  it('has a labelled, required reason field limited to 2000 characters', async () => {
    const html = await render();
    const textarea = /<textarea[^>]*>/.exec(html)?.[0] ?? '';
    expect(textarea).toContain('required');
    const id = /id="([^"]+)"/.exec(textarea)?.[1] ?? '';
    expect(id).not.toBe('');
    expect(html).toMatch(new RegExp(`<label[^>]*for="${id}"[^>]*>Reason<`));
    expect(textarea).toMatch(/maxLength="2000"|maxlength="2000"/);
  });

  it('names the exact action on the confirm button, which starts disabled', async () => {
    const html = await render();
    const button = /<button[^>]*>Block supplier<\/button>/.exec(html)?.[0] ?? '';
    expect(button).not.toBe('');
    expect(button).toContain('disabled');
  });

  it('offers a cancel and never puts initial focus on the confirm button', async () => {
    const html = await render();
    expect(html).toContain('Keep current status');
    expect(html).not.toMatch(/<button[^>]*autofocus[^>]*>Block supplier</i);
  });

  it('renders nothing while closed', async () => {
    expect(await render({ open: false })).toBe('');
  });
});
