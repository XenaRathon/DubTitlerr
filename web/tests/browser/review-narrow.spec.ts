import { expect, test, type Page } from '@playwright/test';
import { openSignedIn, reset } from './helpers';

const FAKE = 60;

/** Pad the inbox with enough episodes to overflow the list; any padded stem opens the first real fixture episode. */
async function padInbox(page: Page) {
  let realStem = '';
  await page.route('**/api/episodes', async (route) => {
    const real = await route.fetch();
    const data = await real.json();
    realStem = data.episodes[0].stem;
    const padding = Array.from({ length: FAKE }, (_, i) => ({
      stem: `pad-${i}`,
      name: `Pad Show S01E${String(i + 1).padStart(2, '0')}`,
      season: 'Season 1',
      show: 'Pad Show',
      pending: 1,
      admitted: 1,
      refused: 0,
    }));
    await route.fulfill({ response: real, json: { ...data, episodes: [...data.episodes, ...padding] } });
  });
  await page.route('**/api/episode?stem=pad-*', (route) => {
    const url = new URL(route.request().url());
    url.searchParams.set('stem', realStem);
    return route.continue({ url: url.toString() });
  });
}

test.beforeEach(async ({ request }) => reset(request));

test('narrow layout: the episode list scrolls inside itself and the editor is brought into view', async ({
  page,
}) => {
  await page.setViewportSize({ width: 940, height: 1000 });
  await padInbox(page);
  await openSignedIn(page, '');
  const list = page.locator('.episode-list');
  const listBox = await list.boundingBox();
  expect(listBox!.height).toBeLessThanOrEqual(1000 * 0.4 + 1);
  await list.locator('.episode', { hasText: 'Pad Show S01E60' }).click();
  const panel = page.locator('section.review-panel');
  await expect(panel.getByRole('heading', { level: 2 })).toBeInViewport();
  await expect(panel).toBeFocused();
});

test('wide layout: choosing an episode does not scroll the page', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await padInbox(page);
  await openSignedIn(page, '');
  await page.locator('.episode-list .episode', { hasText: 'Pad Show S01E05' }).click();
  await expect(page.locator('section.review-panel')).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});
