import { expect, test, type Page } from '@playwright/test';
import { navTo, openSignedIn, reset } from './helpers';

test.beforeEach(async ({ request }) => reset(request));

const episode = (show: string, season: string, name: string, admitted: number, at: string | null = null) => ({
  stem: `/anime/${show}/${season}/${name}`,
  show,
  season,
  name,
  pending: admitted,
  admitted,
  refused: 0,
  oldest_pending_at: at,
});
// Served in the server's own order: most admitted first.
const EPISODES = [
  episode('Neon Harbor', 'Season 1', 'Neon Harbor S01E10', 5, null),
  episode('Alpha Show', 'Season 10', 'Alpha Show S10E01', 3, '2026-10-02T08:00:00Z'),
  episode('Neon Harbor', 'Season 1', 'Neon Harbor S01E02', 2, '2026-09-30T23:59:59Z'),
];

async function mockEpisodes(page: Page) {
  await page.route('**/api/episodes', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ episodes: EPISODES }) }),
  );
}

const names = (page: Page) => page.locator('.episode-list .episode strong').allTextContents();

test('the episode list sorts by episode order and pending count, and remembers the choice', async ({
  page,
}) => {
  await mockEpisodes(page);
  await openSignedIn(page);
  const sort = page.getByLabel('Sort episodes');
  await expect(sort).toHaveValue('default');
  expect(await names(page)).toEqual(['Neon Harbor S01E10', 'Alpha Show S10E01', 'Neon Harbor S01E02']);

  await sort.selectOption('episode');
  await expect
    .poll(() => names(page))
    .toEqual(['Alpha Show S10E01', 'Neon Harbor S01E02', 'Neon Harbor S01E10']);
  await sort.selectOption('pending');
  await expect
    .poll(() => names(page))
    .toEqual(['Neon Harbor S01E10', 'Alpha Show S10E01', 'Neon Harbor S01E02']);
  await expect(sort.locator('option[value="oldest"]')).toHaveText('Oldest pending first');
  await expect(sort.locator('option[value="pending"]')).toHaveText('Most repairs to check');
  await sort.selectOption('oldest');
  await expect
    .poll(() => names(page))
    .toEqual(['Neon Harbor S01E02', 'Alpha Show S10E01', 'Neon Harbor S01E10']);

  await sort.selectOption('episode');
  // The tab keeps its token, so a reload signs straight back in.
  await page.reload();
  await expect(page.getByLabel('Sort episodes')).toHaveValue('episode');
  await expect
    .poll(() => names(page))
    .toEqual(['Alpha Show S10E01', 'Neon Harbor S01E02', 'Neon Harbor S01E10']);
});

test('a sort stored under the old Oldest activity label still restores', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('dubtitlerr_episode_sort', 'oldest'));
  await mockEpisodes(page);
  await openSignedIn(page);
  await expect(page.getByLabel('Sort episodes')).toHaveValue('oldest');
  await expect
    .poll(() => names(page))
    .toEqual(['Neon Harbor S01E02', 'Alpha Show S10E01', 'Neon Harbor S01E10']);
});

test('an unknown stored sort falls back to the default', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('dubtitlerr_episode_sort', 'nonsense');
  });
  await mockEpisodes(page);
  await openSignedIn(page);
  await expect(page.getByLabel('Sort episodes')).toHaveValue('default');
});

test('the in-episode sort is remembered across episodes and reloads', async ({ page }) => {
  await openSignedIn(page);
  await page.getByLabel('Search episodes').fill('Neon Harbor');
  await page.getByRole('button', { name: /Neon Harbor.*S01E01/ }).click();
  await expect(page.getByTestId('evidence')).toBeVisible();
  const lines = page.getByLabel('Sort review lines');
  await expect(lines).toHaveValue('risk');
  await lines.selectOption('time');
  expect(await page.evaluate(() => localStorage.getItem('dubtitlerr_line_sort'))).toBe('time');

  // Opening the episode again keeps the stored order instead of resetting it to risk.
  await page.getByRole('button', { name: /Neon Harbor.*S01E01/ }).click();
  await expect(page.getByTestId('evidence')).toBeVisible();
  await expect(lines).toHaveValue('time');

  // The shared view uses its own order and must not overwrite the inbox preference.
  await navTo(page, /Shared lines/);
  await expect(page.getByLabel('Sort review lines')).toHaveValue('repeated');
  expect(await page.evaluate(() => localStorage.getItem('dubtitlerr_line_sort'))).toBe('time');

  // A reload restores the stored order for the inbox.
  await navTo(page, /Review inbox/);
  await page.reload();
  await page.getByLabel('Search episodes').fill('Neon Harbor');
  await page.getByRole('button', { name: /Neon Harbor.*S01E01/ }).click();
  await expect(page.getByLabel('Sort review lines')).toHaveValue('time');
});
