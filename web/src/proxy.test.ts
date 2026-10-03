import { describe, expect, it } from 'vitest';

import { buildCsp } from './proxy';

describe('buildCsp', () => {
  it('is strict in production', () => {
    const csp = buildCsp('abc', false);
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("'nonce-abc'");
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).not.toContain('ws:');
  });
  it('allows eval and websockets only in dev', () => {
    const csp = buildCsp('abc', true);
    expect(csp).toContain("'unsafe-eval'");
    expect(csp).toContain('ws:');
  });
});
