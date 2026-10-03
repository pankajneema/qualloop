import { expect, test, type Page } from '@playwright/test';

import { apiCreateSupplier, apiLogin, apiPost, DEMO, runToken } from './support';

// Suppliers list: search, filters, sorts, archived toggle, keyset "Load more" (API.md 5, P02 plan 2.6).

async function openList(page: Page, token: string) {
  await page.goto('/suppliers');
  await page.getByRole('searchbox', { name: 'Search suppliers' }).fill(token);
}

function rowsFor(page: Page, token: string) {
  return page.getByRole('table', { name: 'Suppliers' }).getByRole('row').filter({ hasText: token });
}

test.describe('suppliers list', () => {
  test.beforeEach(async ({ page }) => {
    await apiLogin(page, DEMO.approver);
  });

  test('shows a table with an outlined status chip and a single primary action', async ({
    page,
  }) => {
    const token = runToken();
    await apiCreateSupplier(page, { name: `Alpha ${token} Castings`, status: 'on_watch' });
    await page.goto('/suppliers');
    await expect(page.getByRole('heading', { level: 1, name: 'Suppliers' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Add supplier' })).toBeVisible();
    await page.getByRole('searchbox', { name: 'Search suppliers' }).fill(token);
    const row = rowsFor(page, token);
    await expect(row).toHaveCount(1);
    const chip = row.getByTestId('status-chip');
    await expect(chip).toHaveText('On watch');
    await expect(chip).toHaveAttribute('data-variant', 'outlined');
    await expect(chip).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(chip).not.toHaveCSS('border-top-width', '0px');
  });

  test('search narrows the list by name, code and GSTIN, and says so when nothing matches', async ({
    page,
  }) => {
    const token = runToken();
    const a = await apiCreateSupplier(page, { name: `Alpha ${token} Forge`, code: `A-${token}` });
    await apiCreateSupplier(page, { name: `Bravo ${token} Press`, code: `B-${token}` });
    await apiCreateSupplier(page, {
      name: `Gamma ${token} Tools`,
      code: `G-${token}`,
      gstin: `27${token}ZZZZZZZZZ`.slice(0, 15).padEnd(15, 'Z'),
    });
    await openList(page, token);
    await expect(rowsFor(page, token)).toHaveCount(3);

    const search = page.getByRole('searchbox', { name: 'Search suppliers' });
    await search.fill(`${token} forge`);
    await expect(rowsFor(page, token)).toHaveCount(1);
    await expect(rowsFor(page, token)).toContainText('Alpha');

    await search.fill(a.code);
    await expect(rowsFor(page, token)).toHaveCount(1);

    await search.fill(`27${token}ZZZ`);
    await expect(rowsFor(page, token)).toHaveCount(1);
    await expect(rowsFor(page, token)).toContainText('Gamma');

    await search.fill(`${token}-nothing-like-this`);
    await expect(page.getByText(/no suppliers match/i)).toBeVisible();
    await search.fill(token);
    await expect(rowsFor(page, token)).toHaveCount(3);
  });

  test('filters by status and by category and combines them', async ({ page }) => {
    const token = runToken();
    await apiCreateSupplier(page, {
      name: `One ${token}`,
      status: 'approved',
      category: 'bought_out',
    });
    await apiCreateSupplier(page, {
      name: `Two ${token}`,
      status: 'on_watch',
      category: 'raw_material',
    });
    await apiCreateSupplier(page, {
      name: `Three ${token}`,
      status: 'blocked',
      category: 'service',
    });
    await openList(page, token);
    await expect(rowsFor(page, token)).toHaveCount(3);

    await page.getByLabel('Status').selectOption({ label: 'On watch' });
    await expect(rowsFor(page, token)).toHaveCount(1);
    await expect(rowsFor(page, token)).toContainText('Two');

    await page.getByLabel('Status').selectOption({ label: 'All statuses' });
    await page.getByLabel('Category').selectOption({ label: 'Service' });
    await expect(rowsFor(page, token)).toHaveCount(1);
    await expect(rowsFor(page, token)).toContainText('Three');

    await page.getByLabel('Status').selectOption({ label: 'Approved' });
    await expect(page.getByText(/no suppliers match/i)).toBeVisible();
  });

  test('sorts by name, by code and by most recently updated', async ({ page }) => {
    const token = runToken();
    await apiCreateSupplier(page, { name: `Bravo ${token}`, code: `3-${token}` });
    await apiCreateSupplier(page, { name: `charlie ${token}`, code: `1-${token}` });
    const alpha = await apiCreateSupplier(page, { name: `Alpha ${token}`, code: `2-${token}` });
    await openList(page, token);
    const first = () => rowsFor(page, token).first();

    await expect(first()).toContainText('Alpha');
    await page.getByLabel('Sort by').selectOption({ label: 'Code' });
    await expect(first()).toContainText('charlie');
    await apiPost(page, `/suppliers/${alpha.id}/update`, { city: 'Nashik' });
    await page.getByLabel('Sort by').selectOption({ label: 'Recently updated' });
    await expect(first()).toContainText('Alpha');
  });

  test('archived suppliers are hidden until "Show archived" is ticked', async ({ page }) => {
    const token = runToken();
    const gone = await apiCreateSupplier(page, { name: `Closed ${token}` });
    await apiCreateSupplier(page, { name: `Open ${token}` });
    const archived = await apiPost(page, `/suppliers/${gone.id}/archive`, {
      reason: 'Plant closed',
    });
    expect(archived.status()).toBeLessThan(300);
    await openList(page, token);
    await expect(rowsFor(page, token)).toHaveCount(1);
    await expect(rowsFor(page, token)).toContainText('Open');
    await page.getByRole('checkbox', { name: 'Show archived' }).check();
    await expect(rowsFor(page, token).filter({ hasText: 'Closed' })).toHaveCount(1);
  });

  test('"Load more" fetches the next page of 50 until the list ends', async ({ page }) => {
    test.setTimeout(180_000);
    const token = runToken();
    for (let i = 0; i < 55; i += 1) {
      await apiCreateSupplier(page, { name: `Bulk ${String(i).padStart(2, '0')} ${token}` });
    }
    await openList(page, token);
    await expect(rowsFor(page, token)).toHaveCount(50);
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(rowsFor(page, token)).toHaveCount(55);
    await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0);
  });

  test('a supplier name opens its page', async ({ page }) => {
    const token = runToken();
    const made = await apiCreateSupplier(page, { name: `Open Me ${token}` });
    await openList(page, token);
    await rowsFor(page, token)
      .getByRole('link', { name: `Open Me ${token}` })
      .click();
    await expect(page).toHaveURL(new RegExp(`/suppliers/${made.id}`));
    await expect(page.getByRole('heading', { level: 1, name: `Open Me ${token}` })).toBeVisible();
  });
});

test.describe('suppliers list for a viewer', () => {
  test('a viewer can read and search but is not offered any command', async ({ page }) => {
    await apiLogin(page, DEMO.approver);
    const token = runToken();
    await apiCreateSupplier(page, { name: `Read Only ${token}` });
    await page.context().clearCookies();
    await apiLogin(page, DEMO.viewer);
    await openList(page, token);
    await expect(rowsFor(page, token)).toHaveCount(1);
    await expect(page.getByRole('link', { name: 'Add supplier' })).toHaveCount(0);
  });
});
