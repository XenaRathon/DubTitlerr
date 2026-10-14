import { expect, test } from '@playwright/test';
import { ADMIN_TOKEN, expectNoAxeViolations, openSignedIn, reset, REVIEW_TOKEN } from './helpers';

test.beforeEach(async ({ request }) => reset(request));

const queue = async (page: import('@playwright/test').Page, show = 'Neon Harbor', season = '') => {
  await page.getByLabel('Show', { exact: true }).fill(show);
  if (season) await page.getByLabel('Season (optional)').fill(season);
  await page.getByRole('button', { name: 'Queue run' }).click();
};

test('#/runs mounts the run-request page with an empty queue', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await expect(page.getByRole('heading', { name: 'Run requests', level: 1 })).toBeVisible();
  await expect(page.getByText('No requests yet.')).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Runs' }),
  ).toHaveAttribute('aria-current', 'page');
});

test('queueing a run needs the admin token: none entered is a plain prompt, nothing is sent', async ({
  page,
}) => {
  await openSignedIn(page, '#/runs');
  let posts = 0;
  await page.route('**/api/requests', (route) => {
    if (route.request().method() === 'POST') posts++;
    return route.continue();
  });
  await queue(page);
  await expect(page.getByRole('alert')).toContainText(/Admin token required/);
  await expect(page.locator('#runs-admin-token')).toBeFocused();
  expect(posts).toBe(0);
});

test('a wrong admin token is a 403 sentence and queues nothing', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await page.locator('#runs-admin-token').fill('not-the-admin-token');
  await queue(page);
  await expect(page.getByRole('alert')).toContainText(/Admin token required|Not allowed/);
  await expect(page.getByText('No requests yet.')).toBeVisible();
});

test('disabled admin writes read as a server setting, not a typo', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await page.route('**/api/requests', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({
          status: 403,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'admin writes are disabled' }),
        })
      : route.continue(),
  );
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page);
  await expect(page.getByRole('alert')).toContainText(/REVIEW_ADMIN_TOKEN/);
});

test('the admin token travels in a header, never in the JSON body, and is kept for the tab only', async ({
  page,
}) => {
  await openSignedIn(page, '#/runs');
  const seen: { headers: Record<string, string>; body: string }[] = [];
  await page.route('**/api/requests', (route) => {
    const req = route.request();
    if (req.method() === 'POST') seen.push({ headers: req.headers(), body: req.postData() ?? '' });
    return route.continue();
  });
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page, 'Neon Harbor', '1');
  await expect(page.getByText(/Queued as/)).toBeVisible();

  expect(seen).toHaveLength(1);
  expect(seen[0].headers['x-review-admin-token']).toBe(ADMIN_TOKEN);
  expect(seen[0].headers['x-review-token']).toBe(REVIEW_TOKEN);
  expect(seen[0].body).not.toContain(ADMIN_TOKEN);
  expect(JSON.parse(seen[0].body)).toEqual({ show: 'Neon Harbor', season: 1 });

  const stored = await page.evaluate(() => ({
    session: sessionStorage.getItem('dubtitlerr_admin_token'),
    local: Object.keys(localStorage).length,
    cookie: document.cookie,
    url: location.href,
  }));
  expect(stored.session).toBe(ADMIN_TOKEN);
  expect(stored.local).toBe(0);
  expect(stored.cookie).not.toContain(ADMIN_TOKEN);
  expect(stored.url).not.toContain(ADMIN_TOKEN);
});

test('a queued run appears in the list; asking for the same run again names the existing request', async ({
  page,
}) => {
  await openSignedIn(page, '#/runs');
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page, 'Paper Moon', '2');
  await expect(page.getByText(/Queued as/)).toBeVisible();
  const table = page.locator('.runs-table tbody tr');
  await expect(table).toHaveCount(1);
  await expect(table.first()).toContainText('Paper Moon');
  await expect(table.first().locator('.badge')).toHaveText('pending');

  await queue(page, 'Paper Moon', '2');
  await expect(page.getByRole('alert')).toContainText(/Already queued as /);
  await expect(table).toHaveCount(1);
});

test('with no show list, an unknown typed show is refused with the server reason', async ({ page }) => {
  // An empty list means free text; the server is then the one that refuses the name.
  await page.route('**/api/shows', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ shows: [] }) }),
  );
  await openSignedIn(page, '#/runs');
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page, 'No Such Show');
  await expect(page.getByRole('alert')).toContainText(/show directory not found/);
});

test('Refresh picks up a request queued from elsewhere', async ({ page, request }) => {
  await openSignedIn(page, '#/runs');
  await expect(page.getByText('No requests yet.')).toBeVisible();
  const made = await request.post('/api/requests', {
    headers: { 'X-Review-Token': REVIEW_TOKEN, 'X-Review-Admin-Token': ADMIN_TOKEN },
    data: { show: 'Neon Harbor' },
  });
  expect(made.ok()).toBe(true);
  await page.getByRole('button', { name: 'Refresh' }).click();
  await expect(page.locator('.runs-table tbody tr')).toHaveCount(1);
  await expect(page.getByRole('cell', { name: 'Neon Harbor' })).toBeVisible();
});

test('the run-requests page has no accessibility violations', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await expect(page.getByText('No requests yet.')).toBeVisible();
  await expectNoAxeViolations(page);
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page);
  await expect(page.getByText(/Queued as/)).toBeVisible();
  await expectNoAxeViolations(page);
});

// --- the schedule save is a PUT with the admin header (the options adapter must keep the method) -------------------

const seenOn = (page: import('@playwright/test').Page, pattern: string) => {
  const seen: { method: string; headers: Record<string, string>; body: string }[] = [];
  void page.route(pattern, (route) => {
    const req = route.request();
    seen.push({ method: req.method(), headers: req.headers(), body: req.postData() ?? '' });
    return route.continue();
  });
  return seen;
};

test('saving the schedule is a PUT carrying the admin header, with no token in the body', async ({
  page,
  request,
}) => {
  await openSignedIn(page, '#/runs');
  const seen = seenOn(page, '**/api/schedule');
  await expect(page.locator('#runs-open')).toBeVisible();
  await page.getByLabel('Window enabled').check();
  await page.locator('#runs-open').fill('02:00');
  await page.locator('#runs-close').fill('09:00');
  await page.locator('#runs-tz').fill('UTC');
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save schedule' }).click();

  await expect(page.getByText('Schedule saved.')).toBeVisible();
  const put = seen.find((r) => r.method === 'PUT');
  expect(put, 'the save went out as a PUT, not a POST').toBeTruthy();
  expect(put!.headers['x-review-admin-token']).toBe(ADMIN_TOKEN);
  expect(put!.headers['x-review-token']).toBe(REVIEW_TOKEN);
  expect(put!.body).not.toContain(ADMIN_TOKEN);
  expect(JSON.parse(put!.body)).toMatchObject({ enabled: true, open: '02:00', close: '09:00', tz: 'UTC' });
  expect(seen.filter((r) => r.method === 'POST')).toHaveLength(0);

  const stored = await (
    await request.get('/api/schedule', { headers: { 'X-Review-Token': REVIEW_TOKEN } })
  ).json();
  expect(stored).toMatchObject({ enabled: true, open: '02:00', close: '09:00', tz: 'UTC' });
});

test('saving the schedule without the admin token asks for it and sends nothing', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  const seen = seenOn(page, '**/api/schedule');
  await expect(page.locator('#runs-open')).toBeVisible();
  await page.getByRole('button', { name: 'Save schedule' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /Admin token required/ })).toBeVisible();
  expect(seen.filter((r) => r.method !== 'GET')).toHaveLength(0);
});

test('a wrong admin token on the schedule is refused with the 403 sentence', async ({ page }) => {
  await openSignedIn(page, '#/runs');
  await expect(page.locator('#runs-open')).toBeVisible();
  await page.locator('#runs-admin-token').fill('not-the-admin-token');
  await page.getByRole('button', { name: 'Save schedule' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /Admin token required|Not allowed/ })).toBeVisible();
});

test('the show picker lists /api/shows, filters as you type, and refuses a show not on the list', async ({
  page,
}) => {
  await page.route('**/api/shows', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ shows: ['Alpha Show', 'Neon Harbor'] }),
    }),
  );
  let posts = 0;
  const seen: string[] = [];
  await page.route('**/api/requests', (route) => {
    if (route.request().method() === 'POST') {
      posts++;
      seen.push(route.request().postData() ?? '');
    }
    return route.continue();
  });
  await openSignedIn(page, '#/runs');
  const listId = await page.getByLabel('Show', { exact: true }).getAttribute('list');
  expect(listId).toBeTruthy();
  const options = page.locator(`datalist#${listId} option`);
  await expect(options).toHaveCount(2);
  expect(await options.evaluateAll((els) => els.map((el) => (el as HTMLOptionElement).value))).toEqual([
    'Alpha Show',
    'Neon Harbor',
  ]);
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page, 'Neon');
  await expect(page.getByRole('alert')).toContainText(/Pick a show from the list/);
  expect(posts).toBe(0);
  // A listed show sends the same body as before.
  await queue(page, 'Neon Harbor', '1');
  await expect(page.getByRole('status')).toContainText(/Queued as/);
  expect(JSON.parse(seen[0])).toEqual({ show: 'Neon Harbor', season: 1 });
});

test('when the show list fails to load, the field takes free text', async ({ page }) => {
  await page.route('**/api/shows', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'boom' }) }),
  );
  await openSignedIn(page, '#/runs');
  await expect(page.getByText(/Show list unavailable/)).toBeVisible();
  await page.locator('#runs-admin-token').fill(ADMIN_TOKEN);
  await queue(page, 'Neon Harbor');
  await expect(page.getByRole('status')).toContainText(/Queued as/);
});
