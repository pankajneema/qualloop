import { expect, test } from '@playwright/test';

test('home returns 200 and renders the app shell', async ({ page }) => {
  const problems: string[] = [];
  page.on('console', (m) => m.type() === 'error' && problems.push(m.text()));
  page.on('pageerror', (e) => problems.push(e.message));
  const response = await page.goto('/');
  expect(response?.status()).toBe(200);
  const csp = response?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toMatch(/script-src [^;]*'nonce-/);
  expect(response?.headers()['permissions-policy']).toContain('camera=()');
  await expect(page.getByTestId('app-nav')).toContainText('QualLoop');
  await expect(page.getByRole('heading', { level: 1, name: 'QualLoop' })).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(problems, 'no CSP/console errors').toEqual([]);
});
