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

test('Show Advanced reveals the advanced rows and the choice survives a reload', async ({ page }) => {
  await openSignedIn(page, '#/settings/glossary');
  await expect(page.locator('[data-key="MINE_MIN_COUNT"]')).toBeVisible();
  await expect(page.locator('[data-key="ACQUIRE_MIN_SIM"]')).toHaveCount(0);
  const toggle = page.getByRole('checkbox', { name: 'Show Advanced' });
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await expect(page.locator('[data-key="ACQUIRE_MIN_SIM"]')).toBeVisible();
  await expect(page.locator('[data-key="VERIFY_DECISION_TAU"]')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('checkbox', { name: 'Show Advanced' })).toBeChecked();
  await expect(page.locator('[data-key="ACQUIRE_MIN_SIM"]')).toBeVisible();
  await page.getByRole('checkbox', { name: 'Show Advanced' }).uncheck();
  await expect(page.locator('[data-key="ACQUIRE_MIN_SIM"]')).toHaveCount(0);
});

test('editing a field turns No Changes into Save Changes, and Ctrl+S saves it', async ({ page }) => {
  await openSignedIn(page, '#/settings/library');
  await expect(page.getByRole('button', { name: 'No Changes' })).toBeDisabled();
  await page.getByLabel('Require English audio', { exact: true }).uncheck();
  await expect(page.getByRole('button', { name: 'Save Changes' })).toBeEnabled();
  await page.keyboard.press('Control+s');
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'No Changes' })).toBeDisabled();
  const row = page.locator('[data-key="REQUIRE_ENG"]');
  await expect(row).toContainText('Set here');
  await expect(page.getByLabel('Require English audio', { exact: true })).not.toBeChecked();
  await page.reload();
  await expect(page.getByLabel('Require English audio', { exact: true })).not.toBeChecked();
});

test('leaving an edited page asks first: Stay and review keeps the edit, Discard drops it', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/library');
  await page.getByLabel('Require English audio', { exact: true }).uncheck();
  await page.evaluate(() => (location.hash = '#/settings/output'));
  const dialog = page.getByRole('dialog', { name: 'Unsaved changes' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Stay and review' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/#\/settings\/library$/);
  await expect(page.getByLabel('Require English audio', { exact: true })).not.toBeChecked();
  await page.evaluate(() => (location.hash = '#/settings/output'));
  await page
    .getByRole('dialog', { name: 'Unsaved changes' })
    .getByRole('button', { name: 'Discard' })
    .click();
  await expect(page.getByRole('heading', { name: 'Output', level: 1 })).toBeVisible();
  await page.evaluate(() => (location.hash = '#/settings/library'));
  await expect(page.getByLabel('Require English audio', { exact: true })).toBeChecked();
  await expect(page.getByRole('button', { name: 'No Changes' })).toBeDisabled();
});

test('the sidebar also asks before an edited page is left, and a saved page leaves without a question', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/library');
  await page.getByLabel('Require English audio', { exact: true }).uncheck();
  const toggle = page.getByRole('button', { name: 'Toggle navigation' });
  if (await toggle.isVisible()) await toggle.click();
  await page
    .getByRole('navigation', { name: 'Primary navigation' })
    .getByRole('button', { name: 'Glossary' })
    .click();
  await page
    .getByRole('dialog', { name: 'Unsaved changes' })
    .getByRole('button', { name: 'Stay and review' })
    .click();
  await expect(page).toHaveURL(/#\/settings\/library$/);
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await page.evaluate(() => (location.hash = '#/settings/output'));
  await expect(page.getByRole('heading', { name: 'Output', level: 1 })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('a server refusal shows red text under the named field, saves nothing, and keeps the edit', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/transcription');
  const beam = page.getByLabel('Beam size', { exact: true });
  await beam.fill('99');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  const error = page.locator('[data-key="WHISPER_BEAM_SIZE"] .field-error');
  await expect(error).toHaveText('must be between 1 and 20');
  await expect(error).toHaveAttribute('role', 'alert');
  await expect(beam).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByRole('button', { name: 'Save Changes' })).toBeEnabled();
  await beam.fill('lots');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(error).toHaveText('must be a whole number');
  await beam.fill('5');
  await expect(error).toHaveCount(0);
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(page.locator('[data-key="WHISPER_BEAM_SIZE"]')).toContainText('Set here');
});

test('one bad value refuses the whole save: the valid edit beside it is not written', async ({ page }) => {
  await openSignedIn(page, '#/settings/transcription');
  await page.getByLabel('Beam size', { exact: true }).fill('99');
  await page.getByLabel('Whisper model', { exact: true }).fill('large-v3');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.locator('[data-key="WHISPER_BEAM_SIZE"] .field-error')).toHaveText(
    'must be between 1 and 20',
  );
  await page.evaluate(() => (location.hash = '#/settings'));
  await page
    .getByRole('dialog', { name: 'Unsaved changes' })
    .getByRole('button', { name: 'Discard' })
    .click();
  await page.evaluate(() => (location.hash = '#/settings/transcription'));
  await expect(page.locator('[data-key="WHISPER_MODEL"]')).toContainText('Default');
});

test('a stored value can be reset to the container value or the default', async ({ page }) => {
  await openSignedIn(page, '#/settings/transcription');
  await page.getByLabel('Beam size', { exact: true }).fill('5');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.locator('[data-key="WHISPER_BEAM_SIZE"]')).toContainText('Set here');
  await page.getByRole('button', { name: 'Reset Beam size' }).click();
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(page.locator('[data-key="WHISPER_BEAM_SIZE"]')).toContainText('Default');
  await expect(page.getByLabel('Beam size', { exact: true })).toHaveValue('7');
});

test('a category page with editable rows has no accessibility violations, errors shown or not', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/transcription');
  await expectNoAxeViolations(page);
  await page.getByLabel('Beam size', { exact: true }).fill('99');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.locator('[data-key="WHISPER_BEAM_SIZE"] .field-error')).toBeVisible();
  await expectNoAxeViolations(page);
});

test('Cmd+S (Meta+S) saves an edited settings page as Ctrl+S does', async ({ page }) => {
  await openSignedIn(page, '#/settings/library');
  await page.getByLabel('Require English audio', { exact: true }).uncheck();
  await page.keyboard.press('Meta+s');
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'No Changes' })).toBeDisabled();
  await expect(page.locator('[data-key="REQUIRE_ENG"]')).toContainText('Set here');
});
