import { expect, test } from '@playwright/test';
import { expectNoAxeViolations, navTo, openSignedIn } from './helpers';

// Hash routing: the location hash names the view; a deep link survives the login gate; back/forward follow it.
async function signIn(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Use a token instead' }).click();
  await page.getByLabel('Access token').fill('browser-fixture-token');
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
}
const nav = (page: import('@playwright/test').Page) =>
  page.getByRole('navigation', { name: 'Primary navigation' });

test('a deep link while signed out shows the login panel, then keeps the hash and the view', async ({
  page,
}) => {
  await page.goto('/review#/glossary');
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
  expect(new URL(page.url()).hash).toBe('#/glossary');
  await signIn(page);
  await expect(nav(page).getByRole('button', { name: 'Glossary' })).toHaveAttribute('aria-current', 'page');
  expect(new URL(page.url()).hash).toBe('#/glossary');
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toHaveCount(0);
});

test('an unknown hash falls back to the inbox and is normalized', async ({ page }) => {
  await page.goto('/review#/nope');
  await signIn(page);
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  await expect(nav(page).getByRole('button', { name: /Review inbox/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(new URL(page.url()).hash).toBe('#/inbox');
});

test('nav clicks set the hash, mark one item current, and the back button returns', async ({ page }) => {
  await page.goto('/review');
  await signIn(page);
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  if (await page.getByRole('button', { name: 'Toggle navigation' }).isVisible())
    await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await nav(page).getByRole('button', { name: 'Dashboard' }).click();
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
  expect(new URL(page.url()).hash).toBe('#/dashboard');
  await expect(nav(page).locator('[aria-current="page"]')).toHaveCount(1);
  await expect(nav(page).getByRole('button', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');

  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  await expect(nav(page).getByRole('button', { name: /Review inbox/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
});

test('the settings view mounts its page and the glossary view mounts the editor', async ({ page }) => {
  await page.goto('/review#/settings');
  await signIn(page);
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Backend connectivity' })).toBeVisible();
  await expect(page.getByText('Coming soon.')).toHaveCount(0);
  await page.goto('/review#/glossary');
  await expect(page.getByRole('heading', { name: /glossary/i }).first()).toBeVisible();
});

test('the closed mobile drawer is inert; the 768px breakpoint decides when it is a drawer', async ({
  page,
}) => {
  await page.goto('/review');
  await signIn(page);
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  const sidebar = page.locator('aside.sidebar');

  await page.setViewportSize({ width: 800, height: 900 });
  await expect(sidebar).not.toHaveAttribute('inert', '');
  await expect(page.getByRole('button', { name: 'Toggle navigation' })).toBeHidden();

  await page.setViewportSize({ width: 740, height: 900 }); // between the old 650px and the spec's 768px
  await expect(page.getByRole('button', { name: 'Toggle navigation' })).toBeVisible();
  await expect(sidebar).toHaveAttribute('inert', '');
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await expect(sidebar).not.toHaveAttribute('inert', '');
  // Choosing an item closes the drawer again (the open drawer covers the toggle button itself).
  await nav(page).getByRole('button', { name: 'Shared lines' }).click();
  await expect(sidebar).toHaveAttribute('inert', '');
});

test('every hash route renders its own page', async ({ page }) => {
  await openSignedIn(page, '');
  const pages: Array<[string, string, import('@playwright/test').Locator]> = [
    ['#/shared', 'Shared lines', page.getByRole('heading', { name: 'Shared lines', level: 1 })],
    ['#/dashboard', 'Dashboard', page.getByRole('heading', { name: 'Pipeline status' })],
    ['#/glossary', 'Glossary', page.getByRole('region', { name: 'Glossary editor' })],
    ['#/runs', 'Runs', page.getByRole('heading', { name: 'Run requests', level: 1 })],
    ['#/settings', 'Settings', page.getByRole('region', { name: 'Backend connectivity' })],
    ['#/inbox', 'Review inbox', page.getByRole('heading', { name: 'Review inbox', level: 1 })],
  ];
  for (const [hash, label, marker] of pages) {
    await navTo(page, new RegExp(label));
    await expect(marker).toBeVisible();
    expect(new URL(page.url()).hash).toBe(hash);
    await expect(nav(page).locator('[aria-current="page"]')).toHaveCount(1);
    await expect(nav(page).getByRole('button', { name: new RegExp(label) })).toHaveAttribute(
      'aria-current',
      'page',
    );
  }
});

test('every hash route can be opened directly after sign-in', async ({ context }) => {
  for (const [hash, marker] of [
    ['#/dashboard', 'Pipeline status'],
    ['#/runs', 'Run requests'],
    ['#/settings', 'Settings'],
  ] as const) {
    const fresh = await context.newPage(); // a new tab: its own sessionStorage, so the login gate shows again
    await openSignedIn(fresh, hash);
    await expect(fresh.getByRole('heading', { name: marker, level: 1 })).toBeVisible();
    expect(new URL(fresh.url()).hash).toBe(hash);
    await fresh.close();
  }
});

test('a typed hash (not a click) switches the page, and Back returns to the previous one', async ({
  page,
}) => {
  await openSignedIn(page, '#/runs');
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
  await page.evaluate(() => (location.hash = '#/settings'));
  await expect(page.getByRole('region', { name: 'Backend connectivity' })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
  expect(new URL(page.url()).hash).toBe('#/runs');
});

test('the drawer: closed means unreachable by keyboard, open means its buttons take focus', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openSignedIn(page, '');
  const sidebar = page.locator('aside.sidebar');
  await expect(sidebar).toHaveAttribute('inert', '');
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Tab');
    const inside = await page.evaluate(() => !!document.activeElement?.closest('aside.sidebar'));
    expect(inside, `Tab ${i} landed inside the closed drawer`).toBe(false);
  }
  const toggle = page.getByRole('button', { name: 'Toggle navigation' });
  await toggle.focus();
  await page.keyboard.press('Enter');
  await expect(sidebar).not.toHaveAttribute('inert', '');
  const settings = nav(page).getByRole('button', { name: 'Settings' });
  await settings.focus();
  await expect(settings).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: 'Backend connectivity' })).toBeVisible();
  await expect(sidebar).toHaveAttribute('inert', '');
});

test('the navigation has no accessibility violations on the new pages', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
  await expectNoAxeViolations(page);
});
