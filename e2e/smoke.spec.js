import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';


async function login(page) {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible();
  await page.getByLabel('Email').fill('admin@example.com');
  await page.getByLabel('Password').fill('LaunchPilot!123');
  await page.getByRole('button', { name: /open tms master/i }).click();
  await expect(page).toHaveURL(/\/tms\/?$/);
}


test('health endpoint returns ok', async ({ request }) => {
  const response = await request.get('/health');
  expect(response.ok()).toBeTruthy();
  await expect(response.json()).resolves.toMatchObject({
    status: 'ok',
    mode: 'full',
  });
});


test('login reaches the dashboard', async ({ page }) => {
  await login(page);
  await expect(page.getByRole('link', { name: /control tower/i }).first()).toBeVisible();
  await expect(page.getByText('Recent Shipments', { exact: true })).toBeVisible();
});


test('dashboard shell stays readable after going offline', async ({ context, page }) => {
  await login(page);
  await expect(page.getByText('Recent Shipments', { exact: true })).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByRole('link', { name: /control tower/i }).first()).toBeVisible();
  await expect(page.getByText('Recent Shipments', { exact: true })).toBeVisible();
  await context.setOffline(false);
});


test('login page has no serious axe violations @a11y', async ({ page }) => {
  await page.goto('/login');
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});


test('dashboard has no serious axe violations @a11y', async ({ page }) => {
  await login(page);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});
