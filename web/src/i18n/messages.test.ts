import { describe, expect, it } from 'vitest';

import en from '../../messages/en.json';
import hi from '../../messages/hi.json';

function keys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null
      ? keys(v as Record<string, unknown>, `${prefix}${k}.`)
      : [`${prefix}${k}`],
  );
}

function entries(obj: Record<string, unknown>, prefix = ''): [string, unknown][] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null
      ? entries(v as Record<string, unknown>, `${prefix}${k}.`)
      : [[`${prefix}${k}`, v] as [string, unknown]],
  );
}

describe('i18n messages', () => {
  it('en and hi have identical keys', () => {
    expect(keys(hi).sort()).toEqual(keys(en).sort());
  });
  it('all values are non-empty strings', () => {
    for (const bundle of [en, hi]) {
      for (const [key, value] of entries(bundle)) {
        expect(typeof value, key).toBe('string');
        expect((value as string).trim().length, key).toBeGreaterThan(0);
      }
    }
  });
});
