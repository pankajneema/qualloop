import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type Format = {
  formatIndianNumber(n: number): string;
  formatInr(paise: number): string;
  formatDate(instant: string, timeZone: string): string;
};
const format = () => load<Format>('@/lib/format');

describe('Indian number formatting (DESIGN_SPEC copy rules, ADR-013 item 7)', () => {
  it.each([
    [0, '0'],
    [7, '7'],
    [999, '999'],
    [1000, '1,000'],
    [5000, '5,000'],
    [99999, '99,999'],
    [100000, '1,00,000'],
    [420000, '4,20,000'],
    [1234567, '12,34,567'],
    [12345678, '1,23,45,678'],
    [-420000, '-4,20,000'],
  ])('groups %d as %s (lakh and crore, not millions)', async (input, expected) => {
    expect((await format()).formatIndianNumber(input)).toBe(expected);
  });

  it('formats paise as rupees with the rupee sign and Indian grouping (DESIGN_SPEC example)', async () => {
    const { formatInr } = await format();
    expect(formatInr(42_000_000)).toBe('₹4,20,000');
    expect(formatInr(0)).toBe('₹0');
    expect(formatInr(100)).toBe('₹1');
  });

  it('keeps paise visible when the amount is not whole rupees', async () => {
    expect((await format()).formatInr(12_345)).toBe('₹123.45');
  });
});

describe('dates are shown in the plant timezone as "3 Oct 2026"', () => {
  it('formats a plain instant in Asia/Kolkata', async () => {
    expect((await format()).formatDate('2026-10-03T06:00:00Z', 'Asia/Kolkata')).toBe('3 Oct 2026');
  });

  it('crosses midnight with the timezone, not with UTC', async () => {
    const { formatDate } = await format();
    // 20:00 UTC on 2 Oct is 01:30 on 3 Oct in India
    expect(formatDate('2026-10-02T20:00:00Z', 'Asia/Kolkata')).toBe('3 Oct 2026');
    expect(formatDate('2026-10-02T20:00:00Z', 'UTC')).toBe('2 Oct 2026');
  });

  it('does not pad the day and uses the three-letter month', async () => {
    const { formatDate } = await format();
    expect(formatDate('2026-01-05T10:00:00Z', 'Asia/Kolkata')).toBe('5 Jan 2026');
    expect(formatDate('2026-12-25T10:00:00Z', 'Asia/Kolkata')).toBe('25 Dec 2026');
  });
});
