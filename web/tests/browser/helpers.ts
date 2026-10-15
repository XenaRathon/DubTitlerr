import AxeBuilder from '@axe-core/playwright';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const USERNAME = 'reviewer';
export const PASSWORD = 'browser-fixture-password';
export const API_KEY = 'browser-fixture-token';

/** Put the fixture back to its starting state: decisions, queues, glossaries and run requests. */
export async function reset(request: APIRequestContext) {
  const res = await request.post('/__test/reset', { headers: { 'X-Api-Key': API_KEY } });
  expect(res.ok()).toBe(true);
}

/** Fill the sign-in form that is already on screen and submit it. */
export async function signIn(page: Page, username = USERNAME, password = PASSWORD) {
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

/** Open a hash route signed out, then sign in (a deep link keeps its hash through login). */
export async function openSignedIn(page: Page, hash = '') {
  await page.goto('/review' + hash);
  await signIn(page);
  // The sidebar is on screen signed out too; Sign out only renders once the session cookie is set and the workspace loaded.
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
}

/** The sidebar button for a view, opening the mobile drawer first when it is collapsed. */
export async function navTo(page: Page, name: string | RegExp) {
  const toggle = page.getByRole('button', { name: 'Toggle navigation' });
  if (await toggle.isVisible()) await toggle.click();
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name }).click();
}

/** WCAG 2.x A/AA scan of the whole page, expecting zero violations. */
export async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}
