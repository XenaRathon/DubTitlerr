import { expect, test, type Page } from '@playwright/test';
import { ADMIN_TOKEN, REVIEW_TOKEN, expectNoAxeViolations, openSignedIn, reset } from './helpers';

const nav = (page: Page) => page.getByRole('navigation', { name: 'Primary navigation' });
const toggle = (page: Page) => page.getByRole('button', { name: 'Toggle navigation' });
const PAGES: Array<[string, string, string]> = [
  ['#/shared', 'Shared lines', 'Shared lines'],
  ['#/dashboard', 'Dashboard', 'Pipeline status'],
  ['#/glossary', 'Glossary', 'Glossary'],
  ['#/runs', 'Runs', 'Run requests'],
  ['#/settings', 'Settings', 'Settings'],
  ['#/inbox', 'Review inbox', 'Review inbox'],
];

test.beforeEach(async ({ request }) => reset(request));

test('each page title is the level-1 heading, and a route change moves focus to it', async ({ page }) => {
  await openSignedIn(page, '');
  for (const [hash, label, title] of PAGES) {
    if (await toggle(page).isVisible()) await toggle(page).click();
    await nav(page)
      .getByRole('button', { name: new RegExp(label) })
      .click();
    const heading = page.getByRole('heading', { name: title, level: 1 });
    await expect(heading, hash).toBeVisible();
    await expect(heading, `focus after going to ${hash}`).toBeFocused();
    await expect(page.locator('main h1')).toHaveCount(1);
  }
});

test('Skip to content is the first tab stop, lands on <main>, and leaves the route alone', async ({
  page,
}) => {
  await openSignedIn(page, '#/runs');
  await page.reload(); // a fresh page: the token is kept in the tab, and Tab starts from the top of the document
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to content' });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.locator('main#main')).toBeFocused();
  expect(new URL(page.url()).hash).toBe('#/runs');
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
});

test('the open drawer takes focus, shuts the page behind it, and Escape puts focus back on the toggle', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openSignedIn(page, '');
  const shell = page.locator('.main-shell');
  await expect(shell).not.toHaveAttribute('inert', '');

  await toggle(page).click();
  await expect(nav(page).getByRole('button').first()).toBeFocused();
  await expect(shell).toHaveAttribute('inert', '');
  await expect(page.locator('aside.sidebar')).not.toHaveAttribute('inert', '');

  await page.keyboard.press('Escape');
  await expect(page.locator('aside.sidebar')).toHaveAttribute('inert', '');
  await expect(shell).not.toHaveAttribute('inert', '');
  await expect(toggle(page)).toBeFocused();
});

test('choosing a page from the drawer lands focus on that page, not on <body>', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openSignedIn(page, '');
  await toggle(page).click();
  await nav(page).getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeFocused();
  await expect(page.locator('aside.sidebar')).toHaveAttribute('inert', '');
});

test('widening the window while the drawer is open frees the page again', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openSignedIn(page, '');
  await toggle(page).click();
  await expect(page.locator('.main-shell')).toHaveAttribute('inert', '');
  await page.setViewportSize({ width: 1200, height: 800 });
  await expect(page.locator('.main-shell')).not.toHaveAttribute('inert', '');
  await expect(page.locator('aside.sidebar')).not.toHaveAttribute('inert', '');
});

test('declining the discard prompt leaves no extra history entry, so Back still leaves the page', async ({
  page,
}) => {
  await openSignedIn(page, '');
  if (await toggle(page).isVisible()) await toggle(page).click();
  await nav(page).getByRole('button', { name: 'Glossary' }).click();
  await expect(page.getByLabel('New term')).toBeVisible();
  await page.getByLabel('New term').fill('Half typed');
  const before = await page.evaluate(() => history.length);

  page.once('dialog', (d) => void d.dismiss());
  if (await toggle(page).isVisible()) await toggle(page).click();
  await nav(page).getByRole('button', { name: 'Dashboard' }).click();
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => history.length)).toBe(before);
  expect(new URL(page.url()).hash).toBe('#/glossary');

  page.once('dialog', (d) => void d.accept());
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
});

test('a non-canonical hash is normalized after the view switches', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await page.evaluate(() => (location.hash = '#/glossary?x=1'));
  await expect(page.getByRole('region', { name: 'Glossary editor' })).toBeVisible();
  await expect.poll(() => new URL(page.url()).hash).toBe('#/glossary');
});

test('a session that expires mid-page says so on the login panel and keeps the route', async ({ page }) => {
  await openSignedIn(page, '#/glossary');
  await expect(page.getByLabel('New term')).toBeVisible();
  await page.route('**/api/glossary**', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'a token is required' }),
    }),
  );
  await page.getByLabel('New term').fill('lost text');
  await page.getByRole('button', { name: 'Add term' }).click();
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
  const alert = page.getByRole('alert');
  await expect(alert).toContainText(/Sign in again/);
  await expect(alert).not.toContainText(/staged choices are still held/);
  expect(new URL(page.url()).hash).toBe('#/glossary');
});

test('no page scrolls sideways on a phone, even with a populated queue', async ({ page, request }) => {
  const made = await request.post('/api/requests', {
    headers: { 'X-Review-Token': REVIEW_TOKEN, 'X-Review-Admin-Token': ADMIN_TOKEN },
    data: { show: 'Neon Harbor', season: 1, episode_re: '[Ss]0*1[Ee]0*1(?!\\d)' },
  });
  expect(made.ok()).toBe(true);
  await page.setViewportSize({ width: 320, height: 800 });
  await openSignedIn(page, '');
  for (const [hash, label, title] of PAGES) {
    await toggle(page).click();
    await nav(page)
      .getByRole('button', { name: new RegExp(label) })
      .click();
    await expect(page.getByRole('heading', { name: title, level: 1 }), hash).toBeVisible();
    if (hash === '#/runs') await expect(page.locator('.runs-table tbody tr')).toHaveCount(1);
    if (hash === '#/dashboard') await expect(page.locator('.dashboard-table tbody tr')).toHaveCount(4);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${hash} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
  }
  await page.goto('/review#/runs');
  await expect(page.getByRole('region', { name: 'Request queue' })).toHaveAttribute('tabindex', '0');
  await expectNoAxeViolations(page);
});
