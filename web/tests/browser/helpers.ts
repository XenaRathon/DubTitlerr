import AxeBuilder from '@axe-core/playwright';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const REVIEW_TOKEN = 'browser-fixture-token';
export const ADMIN_TOKEN = 'browser-admin-token';

/** Put the fixture back to its starting state: decisions, queues, glossaries and run requests. */
export async function reset(request: APIRequestContext) {
  const res = await request.post('/__test/reset', { headers: { 'X-Review-Token': REVIEW_TOKEN } });
  expect(res.ok()).toBe(true);
}

/** Open a hash route signed out, then unlock with the token (a deep link keeps its hash through login). */
export async function openSignedIn(page: Page, hash = '') {
  await page.goto('/review' + hash);
  await page.getByRole('button', { name: 'Use a token instead' }).click();
  await page.getByLabel('Access token').fill(REVIEW_TOKEN);
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
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
