import { expect, test } from '@playwright/test';
import { API_KEY, expectNoAxeViolations, openSignedIn, reset, signIn } from './helpers';

test.beforeEach(async ({ request }) => reset(request));

async function makeUser(request: import('@playwright/test').APIRequestContext) {
  const made = await request.post('/api/users', {
    headers: { 'X-Api-Key': API_KEY },
    data: { username: 'viewer', password: 'viewer password!', role: 'user' },
  });
  expect([201, 409]).toContain(made.status());
}

test('as a user the Runs page has no request form and no schedule editor', async ({ page, request }) => {
  await makeUser(request);
  await page.goto('/review#/runs');
  await signIn(page, 'viewer', 'viewer password!');
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
  await expect(page.locator('#runs-show')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Queue run' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Schedule' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save schedule' })).toHaveCount(0);
  await expectNoAxeViolations(page);
});

test('as a user the General settings page has no Security or Accounts', async ({ page, request }) => {
  await makeUser(request);
  await page.goto('/review#/settings/general');
  await signIn(page, 'viewer', 'viewer password!');
  await expect(page.getByRole('heading', { name: 'General', level: 1 })).toBeVisible();
  await expect(page.locator('[data-key="REVIEW_PORT"]')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Security' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Accounts' })).toHaveCount(0);
});

test('as an admin the same controls are present', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await expect(page.locator('#runs-show')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Queue run' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Schedule' })).toBeVisible();
  await page.goto('/review#/settings/general');
  await expect(page.locator('[data-key="REVIEW_PORT"]')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Security' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Accounts' })).toBeVisible();
});
