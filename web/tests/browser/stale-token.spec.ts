import { expect, test } from '@playwright/test';

// A token left in sessionStorage that the server no longer accepts (it was regenerated) must not block signing in again.
async function staleTab(page: import('@playwright/test').Page) {
  await page.goto('/review');
  await page.evaluate(() => sessionStorage.setItem('dubtitlerr_review_token', 'stale-token-from-before'));
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
}

test('password sign-in works when the tab holds a stale token', async ({ page }) => {
  await staleTab(page);
  await page.getByLabel('Username').fill('reviewer');
  await page.getByLabel('Password').fill('browser-fixture-password');
  await page.getByLabel('Password').press('Enter');
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible({ timeout: 5000 });
  expect(await page.evaluate(() => sessionStorage.getItem('dubtitlerr_review_token'))).toBe(
    'browser-fixture-token',
  );
});

test('a refused stored token is forgotten, and token mode accepts the right token after a wrong one', async ({
  page,
}) => {
  await staleTab(page);
  expect(await page.evaluate(() => sessionStorage.getItem('dubtitlerr_review_token'))).toBeNull();
  await page.getByRole('button', { name: 'Use a token instead' }).click();
  await expect(page.getByLabel('Access token')).toHaveValue('');
  await page.getByLabel('Access token').fill('another-wrong-token');
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await expect(page.getByRole('alert')).toContainText('Access token not accepted');
  expect(await page.evaluate(() => sessionStorage.getItem('dubtitlerr_review_token'))).toBeNull();
  await page.getByLabel('Access token').fill('browser-fixture-token');
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
});
