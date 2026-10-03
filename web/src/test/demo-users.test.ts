import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { DEMO } from '../../e2e/demo-users';

const seed = readFileSync(join(__dirname, '../../../api/seeds/demo.py'), 'utf8');

describe('E2E demo logins match api/seeds/demo.py', () => {
  it.each(
    Object.entries({
      admin: DEMO.admin,
      quality_approver: DEMO.approver,
      quality: DEMO.quality,
      viewer: DEMO.viewer,
    }),
  )('%s', (key, creds) => {
    const row = new RegExp(`"${key}": \\("([^"]+)", "([^"]+)"\\)`).exec(seed);
    expect(row, `DEMO_USERS["${key}"] not found in api/seeds/demo.py`).not.toBeNull();
    expect([row?.[1], row?.[2]]).toEqual([creds.email, creds.password]);
  });
});
