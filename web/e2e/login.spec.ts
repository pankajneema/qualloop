import { expect, test } from '@playwright/test';

import { apiLogin, apiPost, BASE_URL, DEMO, latestMailBody, runToken, uiLogin } from './support';

// UI contract: docs/build/phases/P02-test-contract.md section 5. Runs against the real compose stack with the demo
// users of api/seeds/demo.py (`make up && make seed`).

test.describe('login (A-93)', () => {
  test('a signed-out visitor to a protected page is sent to /login', async ({ page }) => {
    await page.goto('/suppliers');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole('heading', { level: 1, name: 'Sign in' })).toBeVisible();
  });

  test('the sign-in page has labelled fields, one primary button and a reset link', async ({
    page,
  }) => {
    await page.goto('/login');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(page.getByLabel('Password')).toHaveAttribute('type', 'password');
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeEnabled();
    await expect(page.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute(
      'href',
      '/login/reset',
    );
  });

  test('a wrong password shows what happened and what to do, and keeps the user on the page', async ({
    page,
  }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(DEMO.quality.email);
    await page.getByLabel('Password').fill('definitely-not-the-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    const alert = page.getByRole('alert').filter({ hasText: /email or password/i });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/try again/i);
    await expect(alert).not.toContainText(/something went wrong/i);
    await expect(page).toHaveURL(/\/login/);
  });

  test('an unknown email gets the same message as a wrong password (no account enumeration)', async ({
    page,
  }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(`nobody.${runToken()}@example.test`);
    await page.getByLabel('Password').fill('definitely-not-the-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /email or password/i })).toBeVisible();
  });

  test('a quality user signs in and lands on the suppliers list with the main navigation', async ({
    page,
  }) => {
    await uiLogin(page, DEMO.quality);
    await expect(page.getByRole('heading', { level: 1, name: 'Suppliers' })).toBeVisible();
    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    for (const name of ['Suppliers', 'Parts', 'Imports']) {
      await expect(nav.getByRole('link', { name })).toBeVisible();
    }
  });

  test('signing out returns to /login and the session no longer works', async ({ page }) => {
    await uiLogin(page, DEMO.quality);
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto('/suppliers');
    await expect(page).toHaveURL(/\/login/);
    const me = await page.request.get('/api/v1/me');
    expect(me.status()).toBe(401);
  });

  test('the Hindi locale cookie switches the sign-in page to Hindi', async ({ page, context }) => {
    await context.addCookies([{ name: 'ql_locale', value: 'hi', url: BASE_URL }]);
    await page.goto('/login');
    await expect(page.locator('html')).toHaveAttribute('lang', 'hi');
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toHaveText(/[ऀ-ॿ]/);
    await expect(heading).not.toHaveText('Sign in');
  });
});

test.describe('password reset (A-93)', () => {
  test('asking for a code for an unknown email gives the same answer as for a real one', async ({
    page,
  }) => {
    await page.goto('/login/reset');
    await page.getByLabel('Email').fill(`nobody.${runToken()}@example.test`);
    await page.getByRole('button', { name: 'Send reset code' }).click();
    const status = page.getByRole('status').filter({ hasText: /code/i });
    await expect(status).toBeVisible();
    await expect(status).not.toContainText(/not found|no account|unknown/i);
  });

  test('a new user sets a first password from the emailed code and signs in', async ({
    page,
    browser,
  }) => {
    const email = `e2e.reset.${runToken().toLowerCase()}@example.test`;
    const password = `E2e-New-Passphrase-${runToken()}`;

    // an admin creates the user through the API (no password yet; the reset flow sets the first one)
    const admin = await browser.newPage({ baseURL: BASE_URL });
    await apiLogin(admin, DEMO.admin);
    const created = await apiPost(admin, '/users', { email, name: 'E2E Reset', role: 'quality' });
    expect(created.status(), await created.text()).toBeLessThan(300);
    await admin.close();

    await page.goto('/login');
    await page.getByRole('link', { name: 'Forgot password?' }).click();
    await expect(page).toHaveURL(/\/login\/reset/);
    await page.getByLabel('Email').fill(email);
    await page.getByRole('button', { name: 'Send reset code' }).click();

    const body = await latestMailBody(page, email);
    const code = /\b(\d{6})\b/.exec(body)?.[1];
    expect(code, 'a six digit code in the email').toBeTruthy();

    await page.getByLabel('Code').fill(code ?? '');
    await page.getByLabel('New password').fill(password);
    await page.getByRole('button', { name: 'Set new password' }).click();
    await expect(page.getByRole('status').filter({ hasText: /password/i })).toBeVisible();

    await page.getByRole('link', { name: 'Sign in' }).click();
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/suppliers/);
  });
});
