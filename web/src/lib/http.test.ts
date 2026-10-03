import { describe, expect, it } from 'vitest';

import { load } from '@/test/load';

type Http = {
  readCookie(cookieHeader: string, name: string): string | null;
  commandHeaders(input: { csrf: string | null; idempotencyKey?: string }): Record<string, string>;
  newIdempotencyKey(): string;
};
const http = () => load<Http>('@/lib/http');

describe('command requests (API.md 1.2 CSRF double submit, 1.6 idempotency)', () => {
  it('reads the CSRF cookie out of a cookie header', async () => {
    const { readCookie } = await http();
    expect(readCookie('a=1; ql_csrf=abc.def; b=2', 'ql_csrf')).toBe('abc.def');
    expect(readCookie('ql_csrf=only', 'ql_csrf')).toBe('only');
    expect(readCookie('xql_csrf=no; b=2', 'ql_csrf')).toBeNull();
    expect(readCookie('', 'ql_csrf')).toBeNull();
  });

  it('decodes an encoded cookie value', async () => {
    expect((await http()).readCookie('ql_csrf=a%2Bb%3D', 'ql_csrf')).toBe('a+b=');
  });

  it('sends the CSRF token and JSON content type on every command', async () => {
    const { commandHeaders } = await http();
    expect(commandHeaders({ csrf: 'tok' })).toEqual({
      'Content-Type': 'application/json',
      'X-CSRF-Token': 'tok',
    });
  });

  it('adds the Idempotency-Key only when one is given', async () => {
    const { commandHeaders } = await http();
    const key = '0198f0f0-0000-7000-8000-000000000000';
    expect(commandHeaders({ csrf: 'tok', idempotencyKey: key })['Idempotency-Key']).toBe(key);
    expect('Idempotency-Key' in commandHeaders({ csrf: 'tok' })).toBe(false);
  });

  it('omits the CSRF header when there is no cookie yet (login and password reset)', async () => {
    const headers = (await http()).commandHeaders({ csrf: null });
    expect('X-CSRF-Token' in headers).toBe(false);
  });

  it('makes a hyphenated UUID that differs every time', async () => {
    const { newIdempotencyKey } = await http();
    const keys = new Set(Array.from({ length: 50 }, () => newIdempotencyKey()));
    expect(keys.size).toBe(50);
    for (const key of keys) {
      expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    }
  });
});
