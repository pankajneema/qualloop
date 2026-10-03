import { randomBytes, randomUUID } from 'node:crypto';

import { expect, type APIResponse, type Locator, type Page } from '@playwright/test';

import { DEMO, type Credentials } from './demo-users';

export { DEMO };
export type { Credentials };

export const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000';
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025';

/** A short unique token, so repeated runs against the same database never collide (suppliers, files, e-mails). */
export function runToken(): string {
  return randomBytes(4).toString('hex').toUpperCase();
}

/** Upper-case letters and digits only: valid inside a GSTIN. */
export function gstinFor(): string {
  return `27${randomBytes(5).toString('hex').toUpperCase().slice(0, 9)}A1Z5`;
}

// --- API access through the browser's own cookie jar -------------------------------------------------------------
export async function apiLogin(page: Page, user: Credentials): Promise<void> {
  const res = await page.request.post('/api/v1/auth/login', {
    data: user,
    headers: { Origin: BASE_URL },
  });
  expect(res.status(), `API login for ${user.email}: ${await res.text()}`).toBe(200);
}

async function csrfToken(page: Page): Promise<string> {
  const cookie = (await page.context().cookies()).find((c) => c.name === 'ql_csrf');
  if (!cookie) throw new Error('no ql_csrf cookie: call apiLogin first');
  return cookie.value;
}

export async function apiPost(
  page: Page,
  path: string,
  data: unknown,
  options: { idempotent?: boolean } = {},
): Promise<APIResponse> {
  const headers: Record<string, string> = {
    Origin: BASE_URL,
    'X-CSRF-Token': await csrfToken(page),
  };
  if (options.idempotent) headers['Idempotency-Key'] = randomUUID();
  return page.request.post(`/api/v1${path}`, { data, headers });
}

export type SupplierSeed = {
  code: string;
  name: string;
  category: 'raw_material' | 'bought_out' | 'job_work' | 'service';
  status: 'approved' | 'approved_with_action_plan' | 'on_watch' | 'blocked' | 'inactive';
  city?: string;
  gstin?: string;
};

export async function apiCreateSupplier(
  page: Page,
  seed: Partial<SupplierSeed> & { name: string },
): Promise<{ id: string; code: string; name: string }> {
  const body: SupplierSeed = {
    code: `E2E-${runToken()}${runToken()}`,
    category: 'bought_out',
    status: 'approved',
    city: 'Pune',
    ...seed,
  };
  const res = await apiPost(page, '/suppliers', body);
  expect(res.status(), await res.text()).toBeLessThan(300);
  return (await res.json()) as { id: string; code: string; name: string };
}

// --- UI helpers ---------------------------------------------------------------------------------------------------
export async function uiLogin(page: Page, user: Credentials): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(user.email);
  await page.getByLabel('Password').fill(user.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/suppliers/);
}

/** `<dd>` value next to the `<dt>` label inside the "Import summary" region. */
export function summaryCount(page: Page, label: string): Locator {
  return page
    .getByRole('region', { name: 'Import summary' })
    .locator('dt', { hasText: new RegExp(`^${label}$`) })
    .locator('xpath=following-sibling::dd[1]');
}

export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

// --- mail (the real SMTP path ends in mailpit, ADR-020) ----------------------------------------------------------------
export async function latestMailBody(page: Page, to: string): Promise<string> {
  let id = '';
  await expect
    .poll(
      async () => {
        const res = await page.request.get(
          `${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`,
        );
        const found = ((await res.json()) as { messages: { ID: string }[] }).messages;
        id = found[0]?.ID ?? '';
        return id;
      },
      { message: `an email to ${to}`, timeout: 30_000 },
    )
    .not.toBe('');
  const res = await page.request.get(`${MAILPIT_URL}/api/v1/message/${id}`);
  return ((await res.json()) as { Text: string }).Text;
}

// --- import files --------------------------------------------------------------------------------------------------
export const SUPPLIER_CSV_HEADER = 'Supplier Code,Supplier Name,GSTIN No,City,State,Category';

export type CsvSupplier = {
  code: string;
  name: string;
  gstin: string;
  city: string;
  state?: string;
  category: string;
};

export function supplierCsv(rows: CsvSupplier[]): {
  name: string;
  mimeType: string;
  buffer: Buffer;
} {
  const lines = rows.map((r) =>
    [r.code, r.name, r.gstin, r.city, r.state ?? 'Maharashtra', r.category].join(','),
  );
  return {
    name: `suppliers-${runToken()}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from([SUPPLIER_CSV_HEADER, ...lines].join('\r\n') + '\r\n', 'utf-8'),
  };
}

export const MAP_LABELS: Record<string, string> = {
  Code: 'Supplier Code',
  Name: 'Supplier Name',
  GSTIN: 'GSTIN No',
  City: 'City',
  State: 'State',
  Category: 'Category',
};

export async function mapSupplierColumns(page: Page): Promise<void> {
  for (const [field, column] of Object.entries(MAP_LABELS)) {
    await page.getByLabel(field, { exact: true }).selectOption({ label: column });
  }
}
