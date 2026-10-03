import { expect, test } from '@playwright/test';

import { apiCreateSupplier, apiLogin, DEMO, gstinFor, runToken } from './support';

// Supplier create/edit, status change (ReasonDialog, can_approve only) and contacts (P02 plan 2.6, INV-MST-02, 05).

test.describe('create a supplier', () => {
  test.beforeEach(async ({ page }) => {
    await apiLogin(page, DEMO.quality);
  });

  test('status is required and errors say what to fix', async ({ page }) => {
    await page.goto('/suppliers/new');
    await expect(page.getByRole('heading', { level: 1, name: 'Add supplier' })).toBeVisible();
    await page.getByLabel('Code', { exact: true }).fill(`E2E-${runToken()}`);
    await page.getByLabel('Name', { exact: true }).fill('Needs A Status Ltd');
    await page.getByLabel('GSTIN').fill('27BAD');
    await page.getByLabel('Category').selectOption({ label: 'Bought-out' });
    await page.getByRole('button', { name: 'Create supplier' }).click();

    await expect(page).toHaveURL(/\/suppliers\/new/);
    await expect(page.getByLabel('GSTIN')).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByLabel('Status')).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByText(/15 letters or digits/i)).toBeVisible();
    await expect(page.getByText(/choose a status/i).first()).toBeVisible();
  });

  test('a valid form creates the supplier and opens its page', async ({ page }) => {
    const token = runToken();
    await page.goto('/suppliers/new');
    await page.getByLabel('Code', { exact: true }).fill(`E2E-${token}`);
    await page.getByLabel('Name', { exact: true }).fill(`Created In UI ${token}`);
    await page.getByLabel('GSTIN').fill(gstinFor());
    await page.getByLabel('City').fill('Pune');
    await page.getByLabel('State').fill('Maharashtra');
    await page.getByLabel('Category').selectOption({ label: 'Job work' });
    await page.getByLabel('Status').selectOption({ label: 'Approved' });
    await page.getByRole('button', { name: 'Create supplier' }).click();

    await expect(page).toHaveURL(/\/suppliers\/[0-9a-f-]{36}$/);
    await expect(
      page.getByRole('heading', { level: 1, name: `Created In UI ${token}` }),
    ).toBeVisible();
    await expect(page.getByTestId('status-chip')).toHaveText('Approved');
  });
});

test.describe('change a supplier status', () => {
  test('only a user with can_approve can open the dialog, and it needs a reason', async ({
    page,
  }) => {
    const token = runToken();
    await apiLogin(page, DEMO.approver);
    const supplier = await apiCreateSupplier(page, { name: `Status ${token}`, status: 'approved' });
    await page.goto(`/suppliers/${supplier.id}`);

    await page.getByRole('button', { name: 'Change status' }).click();
    const dialog = page.getByRole('dialog', { name: 'Change status' });
    await expect(dialog).toBeVisible();
    const confirm = dialog.getByRole('button', { name: 'Change status' });
    await dialog.getByLabel('New status').selectOption({ label: 'On watch' });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Reason').fill('   ');
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Reason').fill('Two late lots in September');
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect(dialog).toBeHidden();
    await expect(page.getByTestId('status-chip')).toHaveText('On watch');
    await expect(page.getByText('Two late lots in September')).toBeVisible();
  });

  test('cancelling leaves the status as it was', async ({ page }) => {
    await apiLogin(page, DEMO.approver);
    const supplier = await apiCreateSupplier(page, {
      name: `Keep ${runToken()}`,
      status: 'approved',
    });
    await page.goto(`/suppliers/${supplier.id}`);
    await page.getByRole('button', { name: 'Change status' }).click();
    const dialog = page.getByRole('dialog', { name: 'Change status' });
    await dialog.getByLabel('New status').selectOption({ label: 'Blocked' });
    await dialog.getByLabel('Reason').fill('Not going to do this');
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId('status-chip')).toHaveText('Approved');
  });

  test('a quality user without can_approve cannot change status', async ({ page }) => {
    await apiLogin(page, DEMO.approver);
    const supplier = await apiCreateSupplier(page, {
      name: `Locked ${runToken()}`,
      status: 'approved',
    });
    await page.context().clearCookies();
    await apiLogin(page, DEMO.quality);
    await page.goto(`/suppliers/${supplier.id}`);
    await expect(page.getByRole('button', { name: 'Change status' })).toBeDisabled();
  });
});

test.describe('contacts on the supplier page', () => {
  test('add a contact, see that it needs verification, then disable it with a reason', async ({
    page,
  }) => {
    await apiLogin(page, DEMO.quality);
    const token = runToken();
    const supplier = await apiCreateSupplier(page, { name: `Contacts ${token}` });
    await page.goto(`/suppliers/${supplier.id}`);
    await expect(page.getByRole('heading', { level: 2, name: 'Contacts' })).toBeVisible();

    await page.getByRole('button', { name: 'Add contact' }).click();
    const form = page.getByRole('dialog', { name: 'Add contact' });
    await form.getByLabel('Name', { exact: true }).fill(`Asha ${token}`);
    await form.getByLabel('Role').fill('Quality head');
    await form.getByLabel('Mobile').fill('+919876543210');
    await form.getByLabel('Email').fill(`asha.${token.toLowerCase()}@supplier.example.test`);
    await form.getByRole('button', { name: 'Add contact' }).click();
    await expect(form).toBeHidden();

    const row = page
      .getByRole('table', { name: 'Contacts' })
      .getByRole('row')
      .filter({ hasText: `Asha ${token}` });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText('Needs verification');

    await row.getByRole('button', { name: `Disable Asha ${token}` }).click();
    const dialog = page.getByRole('dialog', { name: 'Disable contact' });
    const confirm = dialog.getByRole('button', { name: 'Disable contact' });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Reason').fill('Left the company');
    await confirm.click();
    await expect(dialog).toBeHidden();
    await expect(row).toContainText('Disabled');
    await expect(row.getByRole('button', { name: `Disable Asha ${token}` })).toHaveCount(0);
  });
});
