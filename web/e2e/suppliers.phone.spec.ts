import { expect, test } from '@playwright/test';

import { apiCreateSupplier, apiLogin, DEMO, horizontalOverflow, runToken } from './support';

// Runs only in the `phone-360` project.

test.describe('suppliers list on a 360 px phone', () => {
  test.beforeEach(async ({ page }) => {
    await apiLogin(page, DEMO.approver); // creating an on_watch supplier needs can_approve (A-116)
  });

  test('lists, searches and filters without sideways scrolling and with 48 px touch targets', async ({
    page,
  }) => {
    const token = runToken();
    await apiCreateSupplier(page, { name: `Phone Alpha ${token}`, status: 'approved' });
    await apiCreateSupplier(page, { name: `Phone Bravo ${token}`, status: 'on_watch' });
    await page.goto('/suppliers');
    await expect(page.getByRole('heading', { level: 1, name: 'Suppliers' })).toBeVisible();

    const search = page.getByRole('searchbox', { name: 'Search suppliers' });
    expect((await search.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(48);
    expect(
      await search.evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
    ).toBeGreaterThanOrEqual(16);
    await search.fill(token);

    const rows = page
      .getByRole('table', { name: 'Suppliers' })
      .getByRole('row')
      .filter({ hasText: token });
    await expect(rows).toHaveCount(2);
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
    const link = rows.first().getByRole('link');
    expect((await link.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(48);

    await page.getByLabel('Status').selectOption({ label: 'On watch' });
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('Bravo');
    await expect(rows.first().getByTestId('status-chip')).toHaveText('On watch');
  });

  test('the bottom navigation stays reachable on the list and opens another screen', async ({
    page,
  }) => {
    await page.goto('/suppliers');
    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    await expect(nav).toBeVisible();
    await nav.getByRole('link', { name: 'Parts' }).click();
    await expect(page).toHaveURL(/\/parts/);
    await expect(page.getByRole('heading', { level: 1, name: 'Parts' })).toBeVisible();
  });
});
