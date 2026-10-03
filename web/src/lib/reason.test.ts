import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type Reason = {
  REASON_MAX: number;
  isValidReason(value: string): boolean;
  reasonError(value: string): 'required' | 'too_long' | null;
};
const reason = () => load<Reason>('@/lib/reason');

describe('reason rule shared by every ReasonDialog (API.md 1.8: 1 to 2000 characters)', () => {
  it('has the documented maximum', async () => {
    expect((await reason()).REASON_MAX).toBe(2000);
  });

  it.each([
    ['an empty reason', '', false],
    ['one space', ' ', false],
    ['only whitespace', '\n\t  ', false],
    ['one character', 'a', true],
    ['a short reason with padding', '  two late lots  ', true],
    ['exactly 2000 characters', 'x'.repeat(2000), true],
    ['2001 characters', 'x'.repeat(2001), false],
  ])('%s', async (_label, value, expected) => {
    expect((await reason()).isValidReason(value)).toBe(expected);
  });

  it('counts the trimmed length, so padding cannot push a short reason over the limit', async () => {
    const { isValidReason } = await reason();
    expect(isValidReason(`${' '.repeat(50)}${'x'.repeat(2000)}${' '.repeat(50)}`)).toBe(true);
  });

  it('names why a reason is refused', async () => {
    const { reasonError } = await reason();
    expect(reasonError('   ')).toBe('required');
    expect(reasonError('x'.repeat(2001))).toBe('too_long');
    expect(reasonError('fine')).toBeNull();
  });
});
