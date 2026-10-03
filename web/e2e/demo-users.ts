/**
 * Demo logins used by the E2E suite. Source of truth: `api/seeds/demo.py` (DEMO_USERS). The vitest test
 * `src/test/demo-users.test.ts` fails if the two drift apart. Local development passwords only; never real.
 */
export type Credentials = { email: string; password: string };

export const DEMO = {
  admin: { email: 'admin@demo.qualloop.test', password: 'Demo-Admin-Pass-2026' },
  approver: { email: 'approver@demo.qualloop.test', password: 'Demo-Approver-Pass-2026' },
  quality: { email: 'quality@demo.qualloop.test', password: 'Demo-Quality-Pass-2026' },
  viewer: { email: 'viewer@demo.qualloop.test', password: 'Demo-Viewer-Pass-2026' },
} as const satisfies Record<string, Credentials>;
