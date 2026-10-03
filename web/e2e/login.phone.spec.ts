import { expect, test } from '@playwright/test';

import { DEMO, horizontalOverflow } from './support';

// Runs only in the `phone-360` project (360 x 740). DESIGN_SPEC: phone targets >= 48 px, inputs never below 16 px,
// < 640 px the navigation becomes a bottom bar.

test.describe('login on a 360 px phone', () => {
  test('the sign-in page fits the screen with comfortable touch targets', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { level: 1, name: 'Sign in' })).toBeVisible();
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
    for (const field of [page.getByLabel('Email'), page.getByLabel('Password')]) {
      const box = await field.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(48);
      const fontSize = await field.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      expect(fontSize).toBeGreaterThanOrEqual(16);
    }
    const button = await page.getByRole('button', { name: 'Sign in' }).boundingBox();
    expect(button?.height ?? 0).toBeGreaterThanOrEqual(48);
  });

  test('signing in works on the phone and the navigation is a bottom bar', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(DEMO.quality.email);
    await page.getByLabel('Password').fill(DEMO.quality.password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/suppliers/);
    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    await expect(nav).toBeVisible();
    const box = await nav.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(box?.width).toBeGreaterThanOrEqual((viewport?.width ?? 360) - 1);
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeGreaterThanOrEqual(
      (viewport?.height ?? 740) - 2,
    );
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
  });

  test('a wrong password shows the same actionable alert on the phone', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(DEMO.quality.email);
    await page.getByLabel('Password').fill('definitely-not-the-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /email or password/i })).toBeVisible();
  });
});
