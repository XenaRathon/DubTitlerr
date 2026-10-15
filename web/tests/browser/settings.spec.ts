import { expect, test, type Page } from '@playwright/test';
import { expectNoAxeViolations, openSignedIn, reset } from './helpers';

test.beforeEach(async ({ request }) => reset(request));

const CATEGORIES = [
  'General',
  'Library',
  'Transcription',
  'Glossary',
  'Repair',
  'Connections',
  'Output',
  'Schedule',
  'Connect',
];

/** The settings links of the sidebar, opening the mobile drawer first when it is collapsed. */
async function sidebarCategories(page: Page) {
  const toggle = page.getByRole('button', { name: 'Toggle navigation' });
  if (await toggle.isVisible()) await toggle.click();
  return page
    .getByRole('navigation', { name: 'Primary navigation' })
    .getByRole('list', { name: 'Settings categories' });
}

test('#/settings shows one card per category, each with a heading and a one-line summary', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings');
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
  const cards = page.locator('.settings-card');
  await expect(cards).toHaveCount(9);
  for (const [i, label] of CATEGORIES.entries()) {
    await expect(cards.nth(i).getByRole('heading', { level: 3, name: label })).toBeVisible();
    await expect(cards.nth(i).locator('p')).not.toHaveText('');
  }
});

test('a card opens its category page, which lists only that category', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await page.locator('.settings-card', { hasText: 'Library' }).click();
  await expect(page).toHaveURL(/#\/settings\/library$/);
  await expect(page.getByRole('heading', { name: 'Library', level: 1 })).toBeVisible();
  await expect(page.locator('[data-key="REQUIRE_ENG"]')).toBeVisible();
  await expect(page.locator('[data-key="SKIP_IF_SRT"]')).toBeVisible();
  await expect(page.locator('[data-key="WHISPER_MODEL"]')).toHaveCount(0);
  await expect(page.locator('[data-key="PLEX_URL"]')).toHaveCount(0);
});

test('the sidebar lists the categories under Settings and highlights the open one', async ({ page }) => {
  await openSignedIn(page, '#/settings/transcription');
  const list = await sidebarCategories(page);
  await expect(list.getByRole('link')).toHaveText(CATEGORIES);
  await expect(list.locator('a[aria-current="page"]')).toHaveText('Transcription');
  await list.getByRole('link', { name: 'Glossary' }).click();
  await expect(page).toHaveURL(/#\/settings\/glossary$/);
  await expect(page.getByRole('heading', { name: 'Glossary', level: 1 })).toBeVisible();
  const again = await sidebarCategories(page);
  await expect(again.locator('a[aria-current="page"]')).toHaveText('Glossary');
  await expect(again.locator('a[aria-current="page"]')).toHaveCount(1);
});

test('the Settings sidebar item returns from a category to the card grid', async ({ page }) => {
  await openSignedIn(page, '#/settings/repair');
  await expect(page.getByRole('heading', { name: 'Repair', level: 1 })).toBeVisible();
  const toggle = page.getByRole('button', { name: 'Toggle navigation' });
  if (await toggle.isVisible()) await toggle.click();
  await page
    .getByRole('navigation', { name: 'Primary navigation' })
    .getByRole('button', { name: 'Settings' })
    .click();
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page.locator('.settings-card')).toHaveCount(9);
});

test('an unknown category falls back to the card grid and the address is normalised', async ({ page }) => {
  await openSignedIn(page, '#/settings/nope');
  await expect(page.locator('.settings-card')).toHaveCount(9);
  await expect.poll(() => new URL(page.url()).hash).toBe('#/settings');
});

test('back and forward move between category pages', async ({ page }) => {
  await openSignedIn(page, '#/settings/library');
  await page.evaluate(() => (location.hash = '#/settings/output'));
  await expect(page.getByRole('heading', { name: 'Output', level: 1 })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Library', level: 1 })).toBeVisible();
});

test('every row shows its value and where the value comes from, and secrets only as set or not set', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/connect');
  await expect(page.locator('[data-key="PLEX_TOKEN"]')).toContainText('Not set');
  await expect(page.locator('[data-key="PLEX_SECTION"]')).toContainText('Default');
  // The fixture sets LONGCATAI_API_KEY in the container environment; it renders in the Bootstrap section of this page.
  await page.goto('/review#/settings/connections');
  const key = page.locator('[data-key="LONGCATAI_API_KEY"]');
  await expect(key.locator('.setting-value')).toHaveText('Set');
  await expect(key).toContainText('From the container');
  const body = (await page.locator('body').innerText()) + (await page.content());
  expect(body).not.toContain('fixture-secret-key-value');
});

test('the card grid and a category page have no accessibility violations', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await expect(page.locator('.settings-card')).toHaveCount(9);
  await expectNoAxeViolations(page);
  await page.locator('.settings-card', { hasText: 'Glossary' }).click();
  await expect(page.locator('[data-key="ACQUIRE_APPLY"]')).toBeVisible();
  await expectNoAxeViolations(page);
});
