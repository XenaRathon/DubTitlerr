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

test('as a user every settings row is read-only and no admin control is offered', async ({
  page,
  request,
}) => {
  await makeUser(request);
  // Show the store-error and restart-pending banners, so their admin buttons would have somewhere to appear.
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, store_error: 'settings.json is not valid JSON', restart_pending: true },
    });
  });
  await page.goto('/review#/settings/library');
  await signIn(page, 'viewer', 'viewer password!');
  const row = page.locator('[data-key="REQUIRE_ENG"]');
  await expect(row).toContainText('Only an admin can change settings');
  await expect(page.getByText('Restart pending')).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'settings.json is not valid JSON' })).toBeVisible();
  await expect(page.locator('.setting-row input, .setting-row select')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'No Changes' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save Changes' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Reset settings' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restart Now' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Test/ })).toHaveCount(0);
  await page.goto('/review#/settings/connections');
  await expect(page.getByRole('heading', { name: 'Connections', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Test/ })).toHaveCount(0);
});

test('as a user the Connections page offers no editing and never shows a key box', async ({
  page,
  request,
}) => {
  await makeUser(request);
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: {
        ...body,
        secrets_writable: true,
        connections: [
          {
            name: 'hosted',
            kind: 'openai',
            url: 'http://127.0.0.1:18842/v1/chat/completions',
            model: 'gpt-x',
            extra_body: { set: false },
            timeout_connect: 10,
            timeout_read: 120,
            api_key: { set: true },
          },
        ],
      },
    });
  });
  const puts: string[] = [];
  page.on('request', (r) => {
    if (r.method() === 'PUT' && r.url().includes('/api/settings')) puts.push(r.url());
  });
  await page.goto('/review#/settings/connections');
  await signIn(page, 'viewer', 'viewer password!');
  await expect(page.getByRole('heading', { name: 'Connections', level: 1 })).toBeVisible();
  const card = page.locator('[data-connection]').first();
  await expect(card).toContainText('API key: Set');
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add connection' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Remove connection/ })).toHaveCount(0);
  const pickers = page.locator('.stages select');
  expect(await pickers.count()).toBeGreaterThan(0);
  for (const picker of await pickers.all()) await expect(picker).toBeDisabled();
  // Ctrl+S reaches save() from anywhere; for a user it must send nothing.
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(500);
  expect(puts).toEqual([]);
});
