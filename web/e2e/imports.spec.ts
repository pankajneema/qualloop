import { expect, test, type Page } from '@playwright/test';

import {
  apiLogin,
  DEMO,
  gstinFor,
  mapSupplierColumns,
  runToken,
  summaryCount,
  supplierCsv,
  uiLogin,
  type CsvSupplier,
} from './support';

// Import wizard (blueprint 8 C3, INV-IMP-01, 05, 06). UI contract: docs/build/phases/P02-test-contract.md section 5.
// Files are generated per run so a re-run never sees "uploaded before" by accident, and every row carries a token.

test.describe.configure({ timeout: 180_000 });

const STEP_NAMES = ['Upload', 'Map columns', 'Validate', 'Preview', 'Confirm', 'Result'];

function row(token: string, n: number, over: Partial<CsvSupplier> = {}): CsvSupplier {
  return {
    code: `E2E-${token}-${n}`,
    name: `E2E ${token} Supplier ${n}`,
    gstin: gstinFor(),
    city: 'Pune',
    category: 'bought_out',
    ...over,
  };
}

async function startImport(page: Page, file: { name: string; mimeType: string; buffer: Buffer }) {
  await page.goto('/imports/new');
  await expect(page.getByRole('heading', { level: 1, name: 'New import' })).toBeVisible();
  await page.getByLabel('What are you importing?').selectOption({ label: 'Suppliers' });
  await page.locator('input[type="file"]').setInputFiles(file);
  await expect(page.getByText(file.name)).toBeVisible();
  await page.getByRole('button', { name: 'Upload file' }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Map columns' })).toBeVisible({
    timeout: 60_000,
  });
}

async function validateAndPreview(page: Page) {
  await mapSupplierColumns(page);
  await page.getByRole('button', { name: 'Validate file' }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Preview' })).toBeVisible({
    timeout: 90_000,
  });
}

test.describe('import wizard', () => {
  test.beforeEach(async ({ page }) => {
    await uiLogin(page, DEMO.quality);
  });

  test('shows the six steps in order and marks the current one', async ({ page }) => {
    await page.goto('/imports/new');
    const steps = page.getByRole('list', { name: 'Import steps' }).getByRole('listitem');
    await expect(steps).toHaveText(STEP_NAMES);
    await expect(steps.nth(0)).toHaveAttribute('aria-current', 'step');
    await expect(page.getByRole('heading', { level: 2, name: 'Upload file' })).toBeVisible();
  });

  test('happy path: upload, map, validate, preview, confirm, result with the report download', async ({
    page,
  }) => {
    const token = runToken();
    const rows = [1, 2, 3, 4].map((n) => row(token, n));
    const file = supplierCsv(rows);

    await startImport(page, file);
    await expect(page.getByRole('alert').filter({ hasText: /uploaded before/i })).toHaveCount(0);
    await expect(
      page.getByRole('list', { name: 'Import steps' }).getByRole('listitem').nth(1),
    ).toHaveAttribute('aria-current', 'step');

    // a required column left unmapped keeps the next step closed (a mapping may be suggested from an earlier import)
    await page.getByLabel('Name', { exact: true }).selectOption({ label: 'Not in file' });
    await expect(page.getByRole('button', { name: 'Validate file' })).toBeDisabled();
    await validateAndPreview(page);

    await expect(summaryCount(page, 'Received')).toHaveText('4');
    await expect(summaryCount(page, 'Valid')).toHaveText('4');
    await expect(summaryCount(page, 'Errors')).toHaveText('0');
    await page.getByRole('button', { name: 'Continue to confirm' }).click();

    await expect(page.getByRole('heading', { level: 2, name: 'Confirm import' })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: /valid rows only/i })).toHaveCount(0);
    await page.getByRole('button', { name: 'Import rows' }).click();

    await expect(page.getByRole('heading', { level: 2, name: 'Import complete' })).toBeVisible({
      timeout: 90_000,
    });
    await expect(summaryCount(page, 'Received')).toHaveText('4');
    await expect(summaryCount(page, 'Imported')).toHaveText('4');
    await expect(summaryCount(page, 'Duplicates')).toHaveText('0');
    await expect(summaryCount(page, 'Errors')).toHaveText('0');

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Download report' }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/);

    // the imported suppliers are on the suppliers list, approved
    await page.getByRole('link', { name: 'View suppliers' }).click();
    await page.getByRole('searchbox', { name: 'Search suppliers' }).fill(`E2E ${token}`);
    const found = page
      .getByRole('table', { name: 'Suppliers' })
      .getByRole('row')
      .filter({ hasText: token });
    await expect(found).toHaveCount(4);
    await expect(found.first().getByTestId('status-chip')).toHaveText('Approved');
  });

  test('error path: errors and duplicates are listed, and a partial import needs an explicit tick', async ({
    page,
  }) => {
    const token = runToken();
    const shared = gstinFor();
    const file = supplierCsv([
      row(token, 1, { gstin: shared }), // row 2: valid
      row(token, 2), // row 3: valid
      row(token, 3, { gstin: shared }), // row 4: duplicate of row 2 (same GSTIN)
      row(token, 4, { gstin: '27BAD' }), // row 5: rejected, GSTIN
      row(token, 5, { category: '' }), // row 6: rejected, category
    ]);

    await startImport(page, file);
    await validateAndPreview(page);

    await expect(summaryCount(page, 'Received')).toHaveText('5');
    await expect(summaryCount(page, 'Valid')).toHaveText('2');
    await expect(summaryCount(page, 'Duplicates')).toHaveText('1');
    await expect(summaryCount(page, 'Errors')).toHaveText('2');

    await page.getByRole('tab', { name: /^Errors \(2\)$/ }).click();
    const errors = page.getByRole('tabpanel');
    await expect(errors.getByRole('row').filter({ hasText: /GSTIN/i })).toHaveCount(1);
    await expect(errors.getByRole('row').filter({ hasText: /category/i })).toHaveCount(1);
    await page.getByRole('tab', { name: /^Duplicates \(1\)$/ }).click();
    await expect(
      page.getByRole('tabpanel').getByRole('row').filter({ hasText: /row 2/i }),
    ).toHaveCount(1);

    await page.getByRole('button', { name: 'Continue to confirm' }).click();
    await expect(page.getByRole('heading', { level: 2, name: 'Confirm import' })).toBeVisible();
    const importRows = page.getByRole('button', { name: 'Import rows' });
    const accept = page.getByRole('checkbox', { name: /valid rows only/i });
    await expect(importRows).toBeDisabled();
    await expect(accept).not.toBeChecked();
    await accept.check();
    await expect(importRows).toBeEnabled();
    await accept.uncheck();
    await expect(importRows).toBeDisabled();
    await accept.check();
    await importRows.click();

    await expect(page.getByRole('heading', { level: 2, name: 'Import complete' })).toBeVisible({
      timeout: 90_000,
    });
    await expect(summaryCount(page, 'Received')).toHaveText('5');
    await expect(summaryCount(page, 'Imported')).toHaveText('2');
    await expect(summaryCount(page, 'Duplicates')).toHaveText('1');
    await expect(summaryCount(page, 'Errors')).toHaveText('2');

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Download report' }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
  });

  test('uploading the same file again shows the file-hash warning before anything is processed', async ({
    page,
  }) => {
    const token = runToken();
    const file = supplierCsv([row(token, 1), row(token, 2)]);

    await startImport(page, file);
    await expect(page.getByRole('alert').filter({ hasText: /uploaded before/i })).toHaveCount(0);
    await page.getByRole('button', { name: 'Cancel import' }).click();

    await startImport(page, file);
    const warning = page.getByRole('alert').filter({ hasText: /uploaded before/i });
    await expect(warning).toBeVisible();
    await expect(warning.getByRole('link', { name: /previous import/i })).toBeVisible();
    // a warning, not a block: the user can still go on
    await expect(page.getByRole('heading', { level: 2, name: 'Map columns' })).toBeVisible();
    await mapSupplierColumns(page);
    await expect(page.getByRole('button', { name: 'Validate file' })).toBeEnabled();
  });

  test('importing the same file twice reports every row of the second run as a duplicate', async ({
    page,
  }) => {
    const token = runToken();
    const file = supplierCsv([row(token, 1), row(token, 2), row(token, 3)]);

    await startImport(page, file);
    await validateAndPreview(page);
    await page.getByRole('button', { name: 'Continue to confirm' }).click();
    await page.getByRole('button', { name: 'Import rows' }).click();
    await expect(page.getByRole('heading', { level: 2, name: 'Import complete' })).toBeVisible({
      timeout: 90_000,
    });
    await expect(summaryCount(page, 'Imported')).toHaveText('3');

    await startImport(page, file);
    await expect(page.getByRole('alert').filter({ hasText: /uploaded before/i })).toBeVisible();
    await validateAndPreview(page);
    await expect(summaryCount(page, 'Valid')).toHaveText('0');
    await expect(summaryCount(page, 'Duplicates')).toHaveText('3');
    await page.getByRole('button', { name: 'Continue to confirm' }).click();
    await expect(page.getByRole('button', { name: 'Import rows' })).toBeDisabled();
    await page.getByRole('checkbox', { name: /valid rows only/i }).check();
    await page.getByRole('button', { name: 'Import rows' }).click();
    await expect(page.getByRole('heading', { level: 2, name: 'Import complete' })).toBeVisible({
      timeout: 90_000,
    });
    await expect(summaryCount(page, 'Imported')).toHaveText('0');
    await expect(summaryCount(page, 'Duplicates')).toHaveText('3');
  });

  test('a completed import appears in the imports list', async ({ page }) => {
    const token = runToken();
    const file = supplierCsv([row(token, 1)]);
    await startImport(page, file);
    await validateAndPreview(page);
    await page.getByRole('button', { name: 'Continue to confirm' }).click();
    await page.getByRole('button', { name: 'Import rows' }).click();
    await expect(page.getByRole('heading', { level: 2, name: 'Import complete' })).toBeVisible({
      timeout: 90_000,
    });

    await page.goto('/imports');
    await expect(page.getByRole('heading', { level: 1, name: 'Imports' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'New import' })).toBeVisible();
    const line = page
      .getByRole('table', { name: 'Imports' })
      .getByRole('row')
      .filter({ hasText: file.name });
    await expect(line).toHaveCount(1);
    await expect(line).toContainText('Completed');
  });
});

test.describe('import wizard permissions', () => {
  test('a viewer is not offered imports', async ({ page }) => {
    await apiLogin(page, DEMO.viewer);
    await page.goto('/imports/new');
    await expect(page.getByRole('button', { name: 'Upload file' })).toHaveCount(0);
    await expect(page.getByRole('alert').filter({ hasText: /permission/i })).toBeVisible();
  });
});
