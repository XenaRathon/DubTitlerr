import { expect, test } from '@playwright/test';
import {
  API_KEY,
  PASSWORD,
  USERNAME,
  expectNoAxeViolations,
  openSignedIn,
  reset,
  signIn,
  signOut,
} from './helpers';

test.beforeEach(async ({ request }) => reset(request));

test('the account menu names who is signed in, changes the password only with the current one, and signs out', async ({
  page,
}) => {
  await openSignedIn(page);
  await page.getByRole('button', { name: 'Account menu' }).click();
  await expect(page.getByRole('region', { name: 'Account' })).toContainText(USERNAME);
  await page.getByLabel('Current password').fill('not the password');
  await page.getByLabel('New password', { exact: true }).fill('a brand new password');
  await page.getByLabel('Confirm new password').fill('a brand new password');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('alert')).toContainText('current password is wrong');
  await page.getByLabel('Current password').fill(PASSWORD);
  await page.getByLabel('New password', { exact: true }).fill(PASSWORD); // put it back: the other specs sign in with it
  await page.getByLabel('Confirm new password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('status')).toContainText('Password changed');
  await signOut(page);
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
});

test('an admin sees Security and Accounts, adds a user, and that user sees neither', async ({
  page,
  request,
}) => {
  await openSignedIn(page, '#/settings');
  await expect(page.getByRole('heading', { name: 'Security' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Accounts' })).toBeVisible();
  await expectNoAxeViolations(page);
  const name = `pat${Date.now() % 100000}`;
  await page.getByLabel('New username').fill(name);
  await page.getByLabel('New password', { exact: true }).fill('pat has a password');
  await page.getByRole('button', { name: 'Add account' }).click();
  await expect(page.getByRole('row', { name: new RegExp(name) })).toBeVisible();
  await signOut(page);
  await signIn(page, name, 'pat has a password');
  await page.goto('/review#/settings');
  await expect(page.getByRole('heading', { name: 'Security' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Accounts' })).toHaveCount(0);
  const refused = await request.get('/api/users', { headers: { 'X-Api-Key': 'wrong' } });
  expect(refused.status()).toBe(401);
});

test('the last admin cannot be demoted or deleted and the page says why', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const row = page.getByRole('row', { name: new RegExp(USERNAME) });
  page.on('dialog', (d) => void d.accept());
  await row.getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByRole('alert')).toContainText('cannot remove or demote the last admin');
  await expect(row).toBeVisible();
});

test('Security shows the key hidden, reveals it on request, and Reset asks before it does anything', async ({
  page,
  request,
}) => {
  await openSignedIn(page, '#/settings');
  const field = page.getByLabel('API key');
  await expect(field).toHaveAttribute('type', 'password');
  await page.getByRole('button', { name: 'Show key' }).click();
  await expect(field).toHaveValue(API_KEY);
  page.once('dialog', (d) => void d.dismiss());
  await page.getByRole('button', { name: 'Reset key' }).click();
  expect((await request.get('/api/episodes', { headers: { 'X-Api-Key': API_KEY } })).status()).toBe(200);
});

test('confirming Reset shows the new key the server issued', async ({ page }) => {
  await page.route('**/api/apikey/reset', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ key: 'mocked-new-key-value' }),
    }),
  );
  await openSignedIn(page, '#/settings');
  page.once('dialog', (d) => void d.accept());
  await page.getByRole('button', { name: 'Reset key' }).click();
  await page.getByRole('button', { name: 'Show key' }).click();
  await expect(page.getByLabel('API key')).toHaveValue('mocked-new-key-value');
  await expect(page.getByRole('region', { name: 'Security' }).getByRole('status')).toContainText(
    'old key no longer works',
  );
});

test('on a phone the Security and Accounts sections do not push the page sideways', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await openSignedIn(page, '#/settings');
  await expect(page.getByRole('row', { name: new RegExp(USERNAME) })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `#/settings overflows by ${overflow}px`).toBeLessThanOrEqual(0);
});

test('the account menu closes on a click outside it and stays open on a click inside', async ({ page }) => {
  await openSignedIn(page);
  const toggle = page.getByRole('button', { name: 'Account menu' });
  await toggle.click();
  const menu = page.getByRole('region', { name: 'Account' });
  await menu.getByLabel('Current password').click();
  await expect(menu).toBeVisible();
  await page.getByRole('heading', { name: 'Review inbox', level: 1 }).click();
  await expect(menu).toHaveCount(0);
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
});
