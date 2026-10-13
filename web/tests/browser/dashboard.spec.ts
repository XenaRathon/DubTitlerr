import { expect, test } from '@playwright/test';
import { expectNoAxeViolations, openSignedIn, reset } from './helpers';

// The visible stage words (Dashboard.svelte STAGE_LABELS); the raw stage names stay in the API.
const STAGES = /^(Transcribed|Repaired|Subtitles added|Failed|Out of date|Needs review)$/;

const header = (page: number, pages: number, total: number) => ({
  builder_heartbeat_age_s: 5,
  last_sweep_end: null,
  current_show: null,
  cache_age_s: 3,
  counts_per_stage: { muxed: total },
  total,
  page,
  limit: 50,
  pages,
});
const episode = (name: string) => ({
  show: 'Fake Show',
  season: 'Season 1',
  episode: name,
  stem: `/fake/${name}`,
  stage: 'muxed',
  last_outcome: 'ok',
  repair_model: null,
  text_version: 12,
  pending_review_count: 0,
  updated_at: 1.7e9,
});
const json = (body: object, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
});
const rows = (page: import('@playwright/test').Page) => page.locator('.dashboard-table tbody tr');

test.beforeEach(async ({ request }) => reset(request));

test('#/dashboard mounts the status dashboard, not a placeholder', async ({ page }) => {
  await openSignedIn(page, '#/dashboard');
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
  await expect(page.getByText('Coming soon.')).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Builder heartbeat' })).toBeVisible();
});

test('the table lists the fixture episodes with a stage badge on each row', async ({ page }) => {
  await openSignedIn(page, '#/dashboard');
  await expect(rows(page)).toHaveCount(4);
  const badges = page.locator('.dashboard-table tbody .badge');
  await expect(badges).toHaveCount(4);
  for (const text of await badges.allTextContents()) expect(text.trim()).toMatch(STAGES);
  await expect(page.getByRole('cell', { name: 'Neon Harbor' }).first()).toBeVisible();
  await expect(page.getByRole('cell', { name: /S02E04/ })).toBeVisible();
  await expect(page.getByRole('status').first()).toContainText(/4 episodes/);
});

test('a warming index shows its message, then the data once the retry succeeds', async ({ page }) => {
  await page.clock.install();
  let hits = 0;
  await page.route(/\/api\/status\?/, async (route) => {
    hits++;
    if (hits === 1) return route.fulfill(json({ error: 'cache warming' }, 503));
    return route.continue();
  });
  await openSignedIn(page, '#/dashboard');
  await expect(page.getByRole('status').first()).toContainText(/warming up/i);
  await expect(rows(page)).toHaveCount(1); // the "No episodes on this page." placeholder row
  await page.clock.fastForward(5100);
  await expect(page.getByRole('status').first()).toContainText(/Updated/);
  await expect(rows(page)).toHaveCount(4);
  expect(hits).toBe(2);
});

test('a cache that stays warming is retried a bounded number of times, then reported', async ({ page }) => {
  await page.clock.install();
  let hits = 0;
  await page.route(/\/api\/status\?/, async (route) => {
    hits++;
    await route.fulfill(json({ error: 'cache warming' }, 503));
  });
  await openSignedIn(page, '#/dashboard');
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
  for (let i = 0; i < 12; i++) {
    await page.clock.fastForward(5100);
    await page.waitForTimeout(60);
  }
  await expect(page.getByRole('alert')).toContainText(/still warming/i);
  expect(hits).toBe(6); // the first request plus five retries
  await page.clock.fastForward(60000);
  await page.waitForTimeout(100);
  expect(hits).toBe(6);
});

test('pagination asks the server for the page that was clicked and marks it current', async ({ page }) => {
  const asked: number[] = [];
  await page.route(/\/api\/status\?/, async (route) => {
    const n = Number(new URL(route.request().url()).searchParams.get('page') ?? '1');
    asked.push(n);
    await route.fulfill(json({ header: header(n, 3, 120), episodes: [episode(`Page${n}Episode`)] }));
  });
  await openSignedIn(page, '#/dashboard');
  await expect(page.getByRole('cell', { name: 'Page1Episode' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous page' })).toBeDisabled();

  await page.getByRole('button', { name: 'Go to page 2' }).click();
  await expect(page.getByRole('cell', { name: 'Page2Episode' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Go to page 2' })).toHaveAttribute('aria-current', 'page');

  await page.getByRole('button', { name: 'Next page' }).click();
  await expect(page.getByRole('cell', { name: 'Page3Episode' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next page' })).toBeDisabled();
  expect(asked.slice(0, 3)).toEqual([1, 2, 3]);
});

test('the show filter is sent to the server and narrows the table', async ({ page }) => {
  const urls: string[] = [];
  await page.route(/\/api\/status\?/, async (route) => {
    urls.push(route.request().url());
    await route.continue();
  });
  await openSignedIn(page, '#/dashboard');
  await expect(rows(page)).toHaveCount(4);
  await page.getByLabel('Show', { exact: true }).fill('Paper Moon');
  await page.getByRole('button', { name: 'Apply filter' }).click();
  await expect(rows(page)).toHaveCount(2);
  for (const cell of await page.locator('.dashboard-table tbody tr td:first-child').allTextContents())
    expect(cell).toBe('Paper Moon');
  expect(urls.some((u) => new URL(u).searchParams.get('show') === 'Paper Moon')).toBe(true);
});

test('a slow older response never overwrites a newer one', async ({ page }) => {
  let calls = 0;
  await page.route(/\/api\/status\?/, async (route) => {
    const mine = ++calls;
    if (mine === 1) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      return route.fulfill(json({ header: header(1, 1, 1), episodes: [episode('STALE-ANSWER')] }));
    }
    return route.fulfill(json({ header: header(1, 1, 1), episodes: [episode('FRESH-ANSWER')] }));
  });
  await openSignedIn(page, '#/dashboard');
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
  // The buttons are disabled while loading, so a second load in flight needs a programmatic submit.
  await page.evaluate(() => (document.querySelector('.dashboard-filter') as HTMLFormElement).requestSubmit());
  await expect(page.getByRole('cell', { name: 'FRESH-ANSWER' })).toBeVisible();
  await page.waitForTimeout(2000); // the slow first response lands now
  await expect(page.getByRole('cell', { name: 'FRESH-ANSWER' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'STALE-ANSWER' })).toHaveCount(0);
});

test('the dashboard has no accessibility violations', async ({ page }) => {
  await openSignedIn(page, '#/dashboard');
  await expect(rows(page)).toHaveCount(4);
  await expectNoAxeViolations(page);
});

test('the page never scrolls sideways: a wide table scrolls inside its own region', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openSignedIn(page, '#/dashboard');
  await expect(rows(page)).toHaveCount(4);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const region = page.getByRole('region', { name: 'Episode status' });
  await expect(region).toBeVisible();
  await expect(region).toHaveAttribute('tabindex', '0'); // keyboard users can scroll it
  await expectNoAxeViolations(page);
});

test('the background refresh uses the applied filter, not text still being typed', async ({ page }) => {
  await page.clock.install();
  const urls: string[] = [];
  await page.route(/\/api\/status\?/, async (route) => {
    urls.push(route.request().url());
    await route.continue();
  });
  await openSignedIn(page, '#/dashboard');
  await expect(rows(page)).toHaveCount(4);
  await page.getByLabel('Show', { exact: true }).fill('Paper Moon'); // typed, never applied
  await page.clock.fastForward(31000);
  await expect.poll(() => urls.length).toBeGreaterThanOrEqual(2);
  expect(urls.at(-1)).not.toContain('show=');
  await expect(rows(page)).toHaveCount(4);

  await page.getByRole('button', { name: 'Apply filter' }).click();
  await expect(rows(page)).toHaveCount(2);
  await page.clock.fastForward(31000);
  await expect.poll(() => urls.length).toBeGreaterThanOrEqual(4);
  expect(urls.at(-1)).toContain('show=Paper+Moon'.replace('+', '%20'));
});

test('a timer refresh does not rewrite the live region', async ({ page }) => {
  await page.clock.install();
  let calls = 0;
  await page.route(/\/api\/status\?/, async (route) => {
    calls++;
    await route.fulfill(
      json({ header: header(1, 1, calls === 1 ? 1 : 2), episodes: [episode(`Row${calls}`)] }),
    );
  });
  await openSignedIn(page, '#/dashboard');
  const live = page.locator('section[aria-label="Status dashboard"] > p[role="status"]');
  await expect(live).toContainText('Updated. 1 episodes');
  await page.evaluate(() => {
    const node = document.querySelector('section[aria-label="Status dashboard"] > p[role="status"]')!;
    (window as unknown as { liveChanges: number }).liveChanges = 0;
    new MutationObserver(() => ((window as unknown as { liveChanges: number }).liveChanges += 1)).observe(
      node,
      {
        childList: true,
        characterData: true,
        subtree: true,
      },
    );
  });
  await page.clock.fastForward(31000);
  await expect(page.getByRole('cell', { name: 'Row2' })).toBeVisible(); // the table did refresh
  expect(await page.evaluate(() => (window as unknown as { liveChanges: number }).liveChanges)).toBe(0);
});
