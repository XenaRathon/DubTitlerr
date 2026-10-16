import { expect, test, type Page } from '@playwright/test';
import { expectNoAxeViolations, openSignedIn, reset, signOut } from './helpers';

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

test('every row shows its value and where it comes from, and a secret only as set or not set', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/connect');
  await expect(page.getByLabel('Plex token', { exact: true })).toHaveAttribute('placeholder', 'Not set');
  await expect(page.locator('[data-key="PLEX_SECTION"]')).toContainText('Default');
  // The fixture sets LONGCATAI_API_KEY in the container environment; it lists under General, in the Bootstrap section.
  await page.goto('/review#/settings/general');
  const key = page.getByRole('region', { name: 'Bootstrap' }).locator('[data-key="LONGCATAI_API_KEY"]');
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

test('saving a restart-only setting opens the Restart required dialog; saving a next-show one does not', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/transcription');
  await page.getByLabel('Whisper model', { exact: true }).fill('large-v3');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.evaluate(() => (location.hash = '#/settings/general'));
  await page.getByLabel('Web UI port', { exact: true }).fill('9001');
  await expect(page.locator('[data-key="REVIEW_PORT"]')).toContainText('Restart required');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  const dialog = page.getByRole('dialog', { name: 'Restart required' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Web UI port');
  await expect(dialog).toContainText('unless-stopped or always');
  await expect(dialog).toContainText('compose port mapping must match');
});

test('Restart Later leaves a restart pending banner until the next start', async ({ page }) => {
  await openSignedIn(page, '#/settings/general');
  await page.getByLabel('Web UI port', { exact: true }).fill('9001');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await page
    .getByRole('dialog', { name: 'Restart required' })
    .getByRole('button', { name: 'Restart Later' })
    .click();
  await expect(page.getByText('Restart pending')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Restart pending')).toBeVisible();
  await expect(page.locator('[data-key="REVIEW_PORT"]')).toContainText('Pending');
});

test('Restart Now asks for a soft stop and the overlay stays until a different boot_id answers', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/general');
  await page.getByLabel('Web UI port', { exact: true }).fill('9001');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  let polls = 0;
  await page.route('**/api/status*', async (route) => {
    polls += 1;
    // The old server keeps answering with its own boot_id while the builder finishes the episode.
    await route.fulfill({
      json: { boot_id: polls < 3 ? 'fixture-boot-1' : 'fixture-boot-2', header: {}, episodes: [] },
    });
  });
  const restart = page.waitForResponse((r) => r.url().endsWith('/api/system/restart'));
  await page
    .getByRole('dialog', { name: 'Restart required' })
    .getByRole('button', { name: 'Restart Now' })
    .click();
  expect((await restart).status()).toBe(202);
  const overlay = page.getByRole('dialog', { name: 'Restarting' });
  await expect(overlay).toContainText('Restarting, finishing the current episode');
  await expect.poll(() => polls, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);
  await expect(overlay).toBeVisible();
  await expect(overlay).toHaveCount(0, { timeout: 15_000 });
  expect(polls).toBeGreaterThanOrEqual(3);
  await expect(page.getByRole('status').filter({ hasText: 'The builder restarted.' })).toBeVisible();
});

/** Save a restart-required change, restart, and let ten minutes pass with the old boot_id still answering. */
async function reachRestartTimeout(page: Page) {
  await page.clock.install();
  await openSignedIn(page, '#/settings/general');
  await page.getByLabel('Web UI port', { exact: true }).fill('9001');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  // The old server never goes away: every poll answers with the boot_id from before the restart.
  await page.route('**/api/status*', (route) =>
    route.fulfill({ json: { boot_id: 'fixture-boot-1', header: {}, episodes: [] } }),
  );
  await page
    .getByRole('dialog', { name: 'Restart required' })
    .getByRole('button', { name: 'Restart Now' })
    .click();
  const overlay = page.getByRole('dialog', { name: 'Restarting' });
  await expect(overlay).toContainText('Restarting, finishing the current episode');
  await page.keyboard.press('Escape');
  await expect(overlay).toBeVisible();
  await page.clock.fastForward('09:50');
  await page.clock.runFor(2_000);
  await expect(overlay).toContainText('Restarting, finishing the current episode');
  await page.clock.fastForward('00:12');
  await page.clock.runFor(2_000);
  await expect(overlay.getByRole('alert')).toContainText('did not come back within 10 minutes');
  await expect(overlay).toContainText('start it by hand');
  return overlay;
}

test('after ten minutes without a new boot_id the overlay says to start the container by hand', async ({
  page,
}) => {
  const overlay = await reachRestartTimeout(page);
  await overlay.getByRole('button', { name: 'Close' }).click();
  await expect(overlay).toHaveCount(0);
});

test('once the ten minutes are up Escape closes the overlay', async ({ page }) => {
  const overlay = await reachRestartTimeout(page);
  await page.keyboard.press('Escape');
  await expect(overlay).toHaveCount(0);
});

test('the restart dialog and the overlay have no accessibility violations', async ({ page }) => {
  await openSignedIn(page, '#/settings/general');
  await page.getByLabel('Web UI port', { exact: true }).fill('9001');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('dialog', { name: 'Restart required' })).toBeVisible();
  await expectNoAxeViolations(page);
});

type Entry = {
  key: string;
  category: string;
  editable: boolean;
  secret: boolean;
  managed_by: string | null;
  advanced: boolean;
};

test('every first-wave setting is editable and every other registry entry is read-only with its value and source', async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem('dubtitlerr.settings.showAdvanced', '1'));
  const schemaResponse = page.waitForResponse((r) => r.url().endsWith('/api/settings/schema'));
  await openSignedIn(page, '#/settings');
  const entries: Entry[] = (await (await schemaResponse).json()).settings;
  expect(entries.length).toBeGreaterThan(150);
  const reasons: Record<string, string> = {
    bootstrap: 'Set in the container environment',
    connections: 'Set through a Connection',
    retired: 'Retired: no longer read',
  };
  // Bootstrap values all list under General, whatever category the registry gives them.
  const pageOf = (e: Entry) => (e.managed_by === 'bootstrap' ? 'general' : e.category);
  let seen = 0;
  for (const category of [...new Set(entries.map(pageOf))]) {
    await page.evaluate((c) => (location.hash = `#/settings/${c}`), category);
    await expect(page).toHaveURL(new RegExp(`#/settings/${category}$`));
    await expect(page.locator('.setting-row').first()).toBeVisible();
    const rows: Record<string, { controls: number; text: string }> = await page.evaluate(() =>
      Object.fromEntries(
        [...document.querySelectorAll('.setting-row')].map((el) => [
          el.getAttribute('data-key') ?? '',
          { controls: el.querySelectorAll('input, select, textarea').length, text: el.textContent ?? '' },
        ]),
      ),
    );
    for (const entry of entries.filter((e) => pageOf(e) === category)) {
      const row = rows[entry.key];
      expect(row, entry.key).toBeDefined();
      if (entry.editable) {
        expect(row.controls, entry.key).toBe(1);
      } else {
        expect(row.controls, entry.key).toBe(0);
        expect(row.text, entry.key).toContain(reasons[entry.managed_by ?? ''] ?? 'edit in a later release');
      }
      expect(row.text, entry.key).toMatch(/Default|From the container|Set here/);
      seen += 1;
    }
  }
  expect(seen).toBe(entries.length);
});

test('a secret is entered in a password field, saved, shown only as Set, kept out of browser storage, and cleared', async ({
  page,
}) => {
  const token = 'plex-token-0123456789abcdef';
  await openSignedIn(page, '#/settings/connect');
  const field = page.getByLabel('Plex token', { exact: true });
  await expect(field).toHaveAttribute('type', 'password');
  await field.fill(token);
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  const row = page.locator('[data-key="PLEX_TOKEN"]');
  await expect(row).toContainText('Set here');
  await expect(field).toHaveValue('');
  await expect(field).toHaveAttribute('placeholder', /Set\./);
  expect((await page.locator('body').innerText()) + (await page.content())).not.toContain(token);
  const stored = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }]));
  expect(stored).not.toContain(token);
  // The webhook token is write-only too: a password field that never carries a value back.
  const webhook = page.getByLabel('Webhook token', { exact: true });
  await expect(webhook).toHaveAttribute('type', 'password');
  await expect(webhook).toHaveValue('');
  await page.getByRole('button', { name: 'Clear Plex token' }).click();
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(field).toHaveAttribute('placeholder', 'Not set');
  await expect(row).not.toContainText('Set here');
});

test('before login is enabled a secret is read-only and says why', async ({ page }) => {
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, secrets_writable: false } });
  });
  await openSignedIn(page, '#/settings/connect');
  const row = page.locator('[data-key="WEBHOOK_TOKEN"]');
  await expect(row).toContainText('available after login is enabled');
  await expect(row).toContainText('Not set');
  await expect(row.locator('input')).toHaveCount(0);
});

test('General lists the bootstrap values, the retired variables still set, and the account tools for an admin', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/general');
  await expect(page.getByRole('region', { name: 'Bootstrap' })).toContainText('Config folder');
  await expect(page.locator('[data-key="CONFIG_DIR"] input')).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Retired environment variables' })).toContainText(
    'REPAIR_PROFILES',
  );
  await expect(page.getByRole('region', { name: 'Security' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Accounts' })).toBeVisible();
});

test('an unusable settings file shows a banner and Reset settings asks the server to start over', async ({
  page,
}) => {
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, store_error: 'settings.json is not valid JSON' } });
  });
  await openSignedIn(page, '#/settings/library');
  await expect(page.getByRole('alert').filter({ hasText: 'settings.json is not valid JSON' })).toBeVisible();
  const reset = page.waitForRequest((r) => r.url().endsWith('/api/settings/reset') && r.method() === 'POST');
  await page.getByRole('button', { name: 'Reset settings' }).click();
  expect((await reset).postDataJSON()).toEqual({ all: true });
});

test('signing out of an edited settings page asks with the Unsaved changes dialog first', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/library');
  await page.getByLabel('Require English audio', { exact: true }).uncheck();
  await signOut(page);
  const dialog = page.getByRole('dialog', { name: 'Unsaved changes' });
  await dialog.getByRole('button', { name: 'Stay and review' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel('Require English audio', { exact: true })).not.toBeChecked();
  await signOut(page);
  await page
    .getByRole('dialog', { name: 'Unsaved changes' })
    .getByRole('button', { name: 'Discard' })
    .click();
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
});

const LOCAL_URL = 'http://127.0.0.1:18842/healthz';
const HOSTED_URL = 'http://127.0.0.1:18842/v1/chat/completions';

async function addConnection(
  page: Page,
  fields: { name: string; kind?: string; url: string; model: string; key?: string },
) {
  await page.getByRole('button', { name: 'Add connection' }).click();
  const card = page.locator('[data-connection]').last();
  await card.getByLabel('Name', { exact: true }).fill(fields.name);
  if (fields.kind) await card.getByLabel('Kind', { exact: true }).selectOption(fields.kind);
  await card.getByLabel('URL', { exact: true }).fill(fields.url);
  await card.getByLabel('Model', { exact: true }).fill(fields.model);
  if (fields.key) await card.getByLabel('API key', { exact: true }).fill(fields.key);
  return card;
}

test('a connection is created, picked for the repair stage, saved and tested with the Test button', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/connections');
  await addConnection(page, { name: 'fixture-local', url: LOCAL_URL, model: 'qwen3-4b-instruct' });
  await page.getByLabel('Repair connection', { exact: true }).selectOption('fixture-local');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(page.getByLabel('Repair connection', { exact: true })).toHaveValue('fixture-local');
  await page.getByRole('button', { name: 'Test connection fixture-local' }).click();
  await expect(page.locator('#conn-0-result')).toContainText(/Connection ok in \d+ ms/);
  await page.reload();
  await expect(page.locator('[data-connection]')).toHaveCount(1);
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('fixture-local');
});

test('a key is write-only, and changing the URL says that the stored key will be cleared', async ({
  page,
}) => {
  const key = 'sk-conn-key-0123456789abcdef';
  await openSignedIn(page, '#/settings/connections');
  const card = await addConnection(page, {
    name: 'hosted',
    kind: 'openai',
    url: HOSTED_URL,
    model: 'gpt-x',
    key,
  });
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(card.getByLabel('API key', { exact: true })).toHaveValue('');
  await expect(card.getByLabel('API key', { exact: true })).toHaveAttribute('placeholder', /Set\./);
  expect((await page.locator('body').innerText()) + (await page.content())).not.toContain(key);
  await card.getByLabel('URL', { exact: true }).fill('http://127.0.0.1:18842/v2/chat/completions');
  await expect(card.getByText('Changing the URL clears the stored key')).toBeVisible();
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(card.getByLabel('API key', { exact: true })).toHaveAttribute('placeholder', 'Not set');
});

test('a link-local URL is refused with red text under the URL field and nothing is saved', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/connections');
  const card = await addConnection(page, {
    name: 'metadata',
    url: 'http://169.254.169.254/latest',
    model: 'm',
  });
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(card.locator('.field-error')).toContainText('link-local');
  await page.reload();
  await expect(page.locator('[data-connection]')).toHaveCount(0);
});

test('a stage with no connection can still test the container environment settings', async ({ page }) => {
  await openSignedIn(page, '#/settings/connections');
  await page.getByRole('button', { name: 'Test repair environment settings' }).click();
  await expect(page.locator('#env-result-repair')).toContainText(/Connection ok in \d+ ms/);
  await expect(page.locator('#env-result-repair')).toHaveAttribute('role', 'status');
  await page.getByRole('button', { name: 'Test verify environment settings' }).click();
  await expect(page.locator('#env-result-verify')).toHaveAttribute('role', 'alert');
});

test('before login is enabled the connection key is read-only and says why', async ({ page }) => {
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: {
        ...body,
        secrets_writable: false,
        connections: [
          {
            name: 'hosted',
            kind: 'openai',
            url: HOSTED_URL,
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
  await openSignedIn(page, '#/settings/connections');
  const card = page.locator('[data-connection]').first();
  await expect(card).toContainText('available after login is enabled');
  await expect(card.locator('input[type="password"]')).toHaveCount(0);
});

test('the Connections page has no accessibility violations with a connection on it', async ({ page }) => {
  await openSignedIn(page, '#/settings/connections');
  await addConnection(page, { name: 'fixture-local', url: LOCAL_URL, model: 'm' });
  await expectNoAxeViolations(page);
});

test('an extra body is write-only: shown as set, kept across saves, replaced only when a new one is typed', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/connections');
  const card = await addConnection(page, {
    name: 'hosted',
    kind: 'openai',
    url: HOSTED_URL,
    model: 'gpt-x',
    key: 'sk-conn-key-0123456789abcdef',
  });
  await card.getByLabel('Replace body', { exact: true }).fill('{"tag": "zz-private-91"}');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(card.locator('.extra-state')).toHaveText('Extra request body: Set');
  await expect(card.getByLabel('Replace body', { exact: true })).toHaveValue('');
  expect(await page.content()).not.toContain('zz-private-91');
  await card.getByLabel('Model', { exact: true }).fill('gpt-y');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  const kept = await (await page.request.get('/api/settings')).json();
  expect(kept.connections[0]).toMatchObject({ model: 'gpt-y', extra_body: { set: true } });
  await card.getByLabel('Replace body', { exact: true }).fill('{}');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await expect(card.locator('.extra-state')).toHaveText('Extra request body: Not set');
});

test('the server refusals show under their own fields: a URL query, a short key, a decision host', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings/connections');
  const card = await addConnection(page, {
    name: 'hosted',
    kind: 'openai',
    url: 'http://127.0.0.1:18842/v1/chat/completions?token=x',
    model: 'gpt-x',
    key: 'short',
  });
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(card.locator('.field-error').filter({ hasText: 'query or fragment' })).toBeVisible();
  await card.getByLabel('URL', { exact: true }).fill(HOSTED_URL);
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(card.locator('.field-error').filter({ hasText: '8 to 512 characters' })).toBeVisible();
  await card.getByLabel('API key', { exact: true }).fill('');
  await card.getByLabel('URL', { exact: true }).fill('https://llm.example.net/v1/chat/completions');
  await page.getByLabel('Decision model connection', { exact: true }).selectOption('hosted');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.locator('.stages .field-error')).toContainText(
    'points at a host decision_client.py will not call (llm.example.net)',
  );
});

test('a connect timeout error and a read timeout error both show', async ({ page }) => {
  await openSignedIn(page, '#/settings/connections');
  const card = await addConnection(page, { name: 'fixture-local', url: LOCAL_URL, model: 'm' });
  await page.route('**/api/settings', (route) =>
    route.request().method() === 'PUT'
      ? route.fulfill({
          status: 400,
          json: {
            errors: {
              'connections.fixture-local.timeout_connect': 'connect timeout must be a number',
              'connections.fixture-local.timeout_read': 'read timeout must be a number',
            },
          },
        })
      : route.continue(),
  );
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(
    card.locator('.field-error').filter({ hasText: 'connect timeout must be a number' }),
  ).toBeVisible();
  await expect(
    card.locator('.field-error').filter({ hasText: 'read timeout must be a number' }),
  ).toBeVisible();
});
