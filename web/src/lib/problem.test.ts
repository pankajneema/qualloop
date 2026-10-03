import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type Described = { title: string; detail: string; fields: Record<string, string> };
type Problem = { describeProblem(body: unknown): Described };
const problem = () => load<Problem>('@/lib/problem');

const apiProblem = {
  type: 'https://qualloop.in/problems/validation-error',
  title: 'Some details need fixing',
  status: 422,
  code: 'validation_error',
  detail: 'GSTIN must have 15 letters or digits. Nothing was saved. Check the GSTIN and try again.',
  instance: '/api/v1/suppliers',
  request_id: '01J0',
  errors: [
    { field: 'gstin', code: 'invalid', message: 'Use 15 letters or digits.' },
    { field: 'reason', code: 'required', message: 'Give a reason for this change.' },
  ],
};

describe('error copy (DESIGN_SPEC: what happened, what we did, what you can do)', () => {
  it('shows the API title, detail and per-field messages', async () => {
    const { describeProblem } = await problem();
    const d = describeProblem(apiProblem);
    expect(d.title).toBe('Some details need fixing');
    expect(d.detail).toContain('Nothing was saved');
    expect(d.fields).toEqual({
      gstin: 'Use 15 letters or digits.',
      reason: 'Give a reason for this change.',
    });
  });

  it.each([[null], [undefined], ['boom'], [42], [{}], [{ status: 500 }]])(
    'never says "Something went wrong" for an unreadable error (%j)',
    async (body) => {
      const { describeProblem } = await problem();
      const d = describeProblem(body);
      const text = `${d.title} ${d.detail}`;
      expect(text).not.toMatch(/something went wrong/i);
      expect(d.title.trim().length).toBeGreaterThan(0);
      expect(d.detail.trim().length).toBeGreaterThan(0);
      expect(d.fields).toEqual({});
    },
  );

  it('keeps the request id for support when the server failed', async () => {
    const { describeProblem } = await problem();
    const d = describeProblem({
      ...apiProblem,
      status: 500,
      code: 'internal_error',
      errors: undefined,
    });
    expect(`${d.title} ${d.detail}`).toContain('01J0');
  });
});
