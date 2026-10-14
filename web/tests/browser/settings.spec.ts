import { expect, test } from '@playwright/test';
import { ADMIN_TOKEN, REVIEW_TOKEN, expectNoAxeViolations, openSignedIn, reset } from './helpers';

test.beforeEach(async ({ request }) => reset(request));

test('#/settings shows the grouped cards, with no inline editing', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
  const cards = page.locator('.settings-card');
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(2);
  for (const card of await cards.all()) await expect(card.getByRole('heading', { level: 3 })).toBeVisible();
  // The fixture sets REPAIR_LLAMACPP_URL; it is reported, and nothing offers to edit it.
  await expect(page.getByText('http://127.0.0.1:18842/healthz')).toBeVisible();
  await expect(page.getByText(/Overrides apply at the next sweep; the builder keeps working/)).toBeVisible();
  await expect(page.locator('.settings-card input, .settings-card textarea')).toHaveCount(0);
});

test('secrets appear only as set or not set, never as a value', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const secrets = page.getByRole('region', { name: 'Secrets' });
  await expect(secrets.getByText('LONGCATAI_API_KEY: set')).toBeVisible();
  await expect(secrets.getByText('COMMANDCODE_API_KEY: not set')).toBeVisible();
  const text = (await page.locator('body').innerText()) + (await page.content());
  expect(text).not.toContain('fixture-secret-key-value');
  expect(text).not.toContain('browser-fixture-token');
  expect(text).not.toContain('browser-fixture-password');
});

test('test connection: a reachable backend reads ok, an unreachable one reads as a failure', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings');
  await page.getByRole('button', { name: 'Test repair connection' }).click();
  await expect(page.locator('#settings-test-repair')).toContainText(/Connection ok in \d+ ms/);
  await expect(page.locator('#settings-test-repair')).toHaveAttribute('role', 'status');

  await page.getByRole('button', { name: 'Test verify connection' }).click();
  const failed = page.locator('#settings-test-verify');
  await expect(failed).toBeVisible();
  await expect(failed).toHaveAttribute('role', 'alert');
  await expect(failed).not.toContainText(/Connection ok/);
});

test('a refused probe request is a readable failure, not a blank result', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await page.route('**/api/settings/test', (route) =>
    route.fulfill({
      status: 429,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'slow down' }),
    }),
  );
  await page.getByRole('button', { name: 'Test acquire connection' }).click();
  await expect(page.locator('#settings-test-acquire')).toHaveAttribute('role', 'alert');
  await expect(page.locator('#settings-test-acquire')).toContainText(/Too many checks/);
});

test('the settings page has no accessibility violations, results shown or not', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await expect(page.locator('.settings-card').first()).toBeVisible();
  await expectNoAxeViolations(page);
  await page.getByRole('button', { name: 'Test verify connection' }).click();
  await expect(page.locator('#settings-test-verify')).toBeVisible();
  await expectNoAxeViolations(page);
});

// --- writes: PUT /api/settings and POST /api/settings/reset carry the method and the admin header ----------------

const seenRequests = (page: import('@playwright/test').Page, pattern: string) => {
  const seen: { method: string; headers: Record<string, string>; body: string }[] = [];
  void page.route(pattern, (route) => {
    const req = route.request();
    seen.push({ method: req.method(), headers: req.headers(), body: req.postData() ?? '' });
    return route.continue();
  });
  return seen;
};

test('GET /api/settings reports profiles, pending and whether writes are possible', async ({ request }) => {
  const res = await request.get('/api/settings', { headers: { 'X-Review-Token': REVIEW_TOKEN } });
  const payload = await res.json();
  expect(payload.profiles).toEqual(['local']);
  expect(payload.pending).toEqual({});
  expect(payload.writable).toBe(true);
});

test('saving sends a PUT with the admin token in a header and never in the body', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const seen = seenRequests(page, '**/api/settings');
  await expect(page.getByLabel('Repair model')).toBeVisible();
  await page.getByLabel('Repair model').fill('browser-test-model');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save settings' }).click();

  await expect(page.getByText(/Saved\./)).toBeVisible();
  const put = seen.find((r) => r.method === 'PUT');
  expect(put, 'a PUT request was sent').toBeTruthy();
  expect(put!.headers['x-review-admin-token']).toBe(ADMIN_TOKEN);
  expect(put!.headers['x-review-token']).toBe(REVIEW_TOKEN);
  expect(put!.headers['content-type']).toContain('application/json');
  expect(put!.body).not.toContain(ADMIN_TOKEN);
  expect(JSON.parse(put!.body)).toEqual({ repair_model: 'browser-test-model' });
  // The page reloads settings after the write and shows the change as pending.
  await expect(page.getByText('pending next sweep: browser-test-model')).toBeVisible();
});

test('a profile is picked from the server list and sent by name only', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const seen = seenRequests(page, '**/api/settings');
  await expect(page.getByLabel('Repair profile').locator('option')).toHaveText([
    '(container default)',
    'local',
  ]);
  await page.getByLabel('Repair profile').selectOption('local');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByText(/Saved\./)).toBeVisible();
  const put = seen.find((r) => r.method === 'PUT')!;
  expect(JSON.parse(put.body)).toEqual({ repair_profile: 'local' });
  expect(put.body).not.toMatch(/http|127\.0\.0\.1/);
});

test('Reset overrides is a POST with the admin header and no token in a body', async ({ page, request }) => {
  await request.put('/api/settings', {
    headers: { 'X-Review-Token': REVIEW_TOKEN, 'X-Review-Admin-Token': ADMIN_TOKEN },
    data: { repair_model: 'about-to-be-reset' },
  });
  await openSignedIn(page, '#/settings');
  await expect(page.getByText('pending next sweep: about-to-be-reset')).toBeVisible();
  const seen = seenRequests(page, '**/api/settings/reset');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  page.once('dialog', (d) => void d.accept());
  await page.getByRole('button', { name: 'Reset overrides' }).click();

  await expect(page.getByText('Overrides cleared.')).toBeVisible();
  expect(seen).toHaveLength(1);
  expect(seen[0].method).toBe('POST');
  expect(seen[0].headers['x-review-admin-token']).toBe(ADMIN_TOKEN);
  expect(seen[0].body).not.toContain(ADMIN_TOKEN);
  await expect(page.getByText(/pending next sweep/)).toHaveCount(0);
});

test('saving without an admin token asks for it and sends nothing', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const seen = seenRequests(page, '**/api/settings');
  await page.getByLabel('Repair model').fill('some-model');
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /Admin token required/ })).toBeVisible();
  expect(seen.filter((r) => r.method === 'PUT')).toHaveLength(0);
});

test('a wrong admin token is refused by the server and nothing is written', async ({ page, request }) => {
  await openSignedIn(page, '#/settings');
  await page.getByLabel('Repair model').fill('some-model');
  await page.locator('#settings-admin-token').fill('not-the-admin-token');
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /Admin token required|Not allowed/ })).toBeVisible();
  const payload = await (
    await request.get('/api/settings', { headers: { 'X-Review-Token': REVIEW_TOKEN } })
  ).json();
  expect(payload.overrides).toEqual({});
});

test('a model name the server would refuse is stopped in the form', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const seen = seenRequests(page, '**/api/settings');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByLabel('Repair model').fill('bad model; rm -rf /');
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /Repair model/ })).toBeVisible();
  expect(seen.filter((r) => r.method === 'PUT')).toHaveLength(0);
});

test('when the server says writes are disabled the form is replaced by the reason', async ({ page }) => {
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const res = await route.fetch();
    const payload = await res.json();
    await route.fulfill({
      response: res,
      json: { ...payload, writable: false, writable_reason: 'REPAIR_PROFILES is not valid JSON' },
    });
  });
  await openSignedIn(page, '#/settings');
  await expect(page.getByText(/Writes are disabled on this server/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save settings' })).toHaveCount(0);
});

test('the edit form has no accessibility violations', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await expect(page.getByRole('button', { name: 'Save settings' })).toBeVisible();
  await expectNoAxeViolations(page);
});

// GET /api/settings with the server's allow-lists replaced, everything else as the fixture sent it.
async function withAllowLists(page: import('@playwright/test').Page, lists: Record<string, string[]>) {
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), ...lists } });
  });
}

test('the verify backend and decision model offer only what the server allows', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  await expect(page.getByLabel('Verify backend').locator('option')).toHaveText([
    '(container default)',
    'llamacpp',
    'ollama',
    'decision',
  ]);
  await expect(page.getByLabel('Verify decision model').locator('option')).toHaveText([
    '(container default)',
    'typesafe/jev',
    'acme/judge-1',
  ]);
  const seen = seenRequests(page, '**/api/settings');
  await page.getByLabel('Verify backend').selectOption('decision');
  await page.getByLabel('Verify decision model').selectOption('acme/judge-1');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByText(/Saved\./)).toBeVisible();
  const put = seen.find((r) => r.method === 'PUT')!;
  expect(JSON.parse(put.body)).toEqual({ verify_backend: 'decision', verify_decision_model: 'acme/judge-1' });
});

test('with no decision models enabled the page says how to enable them instead of offering a field', async ({
  page,
}) => {
  await withAllowLists(page, { allowed_decision_models: [] });
  await openSignedIn(page, '#/settings');
  await expect(
    page.getByText('No decision models are enabled on this server; set RUNTIME_DECISION_MODELS'),
  ).toBeVisible();
  await expect(page.getByLabel('Verify decision model')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save settings' })).toBeVisible();
  await expectNoAxeViolations(page);
});

test('a backend the server refuses comes back as a readable sentence naming the env var', async ({
  page,
}) => {
  // The page is told openai is allowed; the server's own list (the fixture's RUNTIME_VERIFY_BACKENDS) is not.
  await withAllowLists(page, { allowed_verify_backends: ['llamacpp', 'openai'] });
  await openSignedIn(page, '#/settings');
  await page.getByLabel('Verify backend').selectOption('openai');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save settings' }).click();
  const alert = page.getByRole('alert').filter({ hasText: /RUNTIME_VERIFY_BACKENDS/ });
  await expect(alert).toBeVisible();
  await expect(alert).toContainText('Not allowed on this server: verify backend.');
  await expect(page.getByText(/Saved\./)).toHaveCount(0);
});

// --- acquire apply: unset means apply, so the toggle starts on and a save of another field leaves it alone ---------

test('the acquire-apply toggle starts on when nothing is set, with its source and timing', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const toggle = page.getByLabel('Apply acquired names');
  await expect(toggle).toBeChecked();
  await expect(page.locator('#settings-acquire-apply-note')).toContainText(
    'Currently on (from the default). A change takes effect at the next sweep.',
  );
  await expectNoAxeViolations(page);
});

test('saving another field never writes acquire_apply while the toggle is untouched', async ({ page }) => {
  await openSignedIn(page, '#/settings');
  const seen = seenRequests(page, '**/api/settings');
  await page.getByLabel('Repair model').fill('browser-test-model');
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByText(/Saved\./)).toBeVisible();
  expect(JSON.parse(seen.find((r) => r.method === 'PUT')!.body)).toEqual({ repair_model: 'browser-test-model' });
});

test('turning the toggle off sends acquire_apply:false and shows it from the runtime file, pending', async ({
  page,
}) => {
  await openSignedIn(page, '#/settings');
  const seen = seenRequests(page, '**/api/settings');
  await page.getByLabel('Apply acquired names').uncheck();
  await page.locator('#settings-admin-token').fill(ADMIN_TOKEN);
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByText(/Saved\./)).toBeVisible();
  expect(JSON.parse(seen.find((r) => r.method === 'PUT')!.body)).toEqual({ acquire_apply: false });
  await expect(page.getByLabel('Apply acquired names')).not.toBeChecked();
  await expect(page.locator('#settings-acquire-apply-note')).toContainText('Currently off (from the runtime file)');
  await expect(page.getByText('pending next sweep: off')).toBeVisible();
});
