import { describe, expect, it } from 'vitest';

import en from '../../messages/en.json';
import hi from '../../messages/hi.json';

/** Namespaces the P02 screens read (docs/build/phases/P02-test-contract.md, section 5). */
const P02_NAMESPACES = ['common', 'login', 'suppliers', 'contacts', 'parts', 'imports'] as const;

type Bundle = Record<string, unknown>;

function leaves(value: unknown, prefix: string): [string, string][] {
  if (typeof value === 'string') return [[prefix, value]];
  if (typeof value === 'object' && value !== null) {
    return Object.entries(value as Bundle).flatMap(([k, v]) =>
      leaves(v, prefix ? `${prefix}.${k}` : k),
    );
  }
  return [];
}

const DEVANAGARI = /[ऀ-ॿ]/;

describe('P02 message namespaces', () => {
  it.each(P02_NAMESPACES)('%s exists in English and Hindi with identical keys', (ns) => {
    const e = (en as Bundle)[ns];
    const h = (hi as Bundle)[ns];
    expect(e, `en.${ns}`).toBeTypeOf('object');
    expect(h, `hi.${ns}`).toBeTypeOf('object');
    const enKeys = leaves(e, ns)
      .map(([k]) => k)
      .sort();
    const hiKeys = leaves(h, ns)
      .map(([k]) => k)
      .sort();
    expect(enKeys.length).toBeGreaterThan(0);
    expect(hiKeys).toEqual(enKeys);
  });

  it.each(P02_NAMESPACES)('%s has no empty or placeholder strings', (ns) => {
    for (const bundle of [en, hi]) {
      const strings = leaves((bundle as Bundle)[ns], ns);
      expect(strings.length, `${ns} has strings`).toBeGreaterThan(0);
      for (const [key, text] of strings) {
        expect(text.trim().length, key).toBeGreaterThan(0);
        expect(text, key).not.toMatch(/^(TODO|TBD|XXX|lorem)/i);
      }
    }
  });

  it('Hindi phrases are translated, not copied from English', () => {
    const untranslated: string[] = [];
    expect(P02_NAMESPACES.flatMap((ns) => leaves((en as Bundle)[ns], ns)).length).toBeGreaterThan(
      0,
    );
    const hiByKey = new Map(P02_NAMESPACES.flatMap((ns) => leaves((hi as Bundle)[ns], ns)));
    for (const ns of P02_NAMESPACES) {
      for (const [key, english] of leaves((en as Bundle)[ns], ns)) {
        const hindi = hiByKey.get(key) ?? '';
        const isPhrase = /\s/.test(english.trim());
        if (isPhrase && !DEVANAGARI.test(hindi)) untranslated.push(key);
      }
    }
    expect(untranslated).toEqual([]);
  });

  it('error copy never uses the banned phrase (DESIGN_SPEC copy rules)', () => {
    expect(P02_NAMESPACES.flatMap((ns) => leaves((en as Bundle)[ns], ns)).length).toBeGreaterThan(
      0,
    );
    for (const bundle of [en, hi]) {
      for (const ns of P02_NAMESPACES) {
        for (const [key, text] of leaves((bundle as Bundle)[ns], ns)) {
          expect(text, key).not.toMatch(/something went wrong/i);
        }
      }
    }
  });
});
