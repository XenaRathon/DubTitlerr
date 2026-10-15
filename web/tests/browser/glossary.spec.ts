import { expect, test, type Page } from '@playwright/test';
import { API_KEY, expectNoAxeViolations, reset, signIn } from './helpers';

async function openGlossary(page: Page) {
  await page.goto('/review#/glossary');
  await signIn(page);
  await expect(page.getByRole('region', { name: 'Glossary editor' })).toBeVisible();
  await expect(page.getByLabel('New term')).toBeVisible();
}
const add = async (page: Page, term: string) => {
  await page.getByLabel('New term').fill(term);
  await page.getByRole('button', { name: 'Add term' }).click();
};

test('a 409 version conflict is a red alert, not a green success notice', async ({ page }) => {
  await openGlossary(page);
  await page.route('**/api/glossary', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'version conflict', version: 'abc' }),
    });
  });
  await add(page, 'Conflicted');
  await expect(page.getByRole('alert')).toContainText(/conflict/i);
  await expect(page.locator('.notice.success')).toHaveCount(0);
});

test('400, 404 and 503 answers read as plain sentences', async ({ page }) => {
  await openGlossary(page);
  const cases: Array<[number, object, RegExp]> = [
    [503, { error: 'glossary busy' }, /glossary busy, try again/],
    [400, { error: 'term already exists' }, /Invalid request: term already exists/],
    [404, { error: 'no such glossary' }, /Unknown show: no such glossary/],
  ];
  for (const [status, body, expected] of cases) {
    await page.route('**/api/glossary', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await add(page, `Case${status}`);
    await expect(page.getByRole('alert')).toContainText(expected);
    await page.unroute('**/api/glossary');
  }
});

test('submitting twice in one tick sends one request', async ({ page }) => {
  await openGlossary(page);
  let posts = 0;
  await page.route('**/api/glossary', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    posts++;
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, version: 'v', reapply_hint: true }),
    });
  });
  await page.getByLabel('New term').fill('Twice');
  await page.evaluate(() => {
    const form = document.querySelector('.glossary-add') as HTMLFormElement;
    form.requestSubmit();
    form.requestSubmit();
  });
  await expect(page.locator('.notice.success').first()).toBeVisible();
  expect(posts).toBe(1);
});

test('deleting a term leaves focus on the search field, not on the page body', async ({ page }) => {
  await openGlossary(page);
  const term = `FocusProbe${Date.now()}`;
  await add(page, term);
  await expect(page.getByRole('cell', { name: term, exact: true })).toBeVisible();
  page.once('dialog', (d) => void d.accept());
  await page
    .getByRole('row', { name: new RegExp(term) })
    .getByRole('button', { name: 'Delete' })
    .click();
  await expect(page.getByRole('cell', { name: term, exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Search terms')).toBeFocused();
});

test('leaving the glossary with unsaved text asks first; declining stays put', async ({ page }) => {
  await openGlossary(page);
  await page.getByLabel('New term').fill('Half typed');
  const toDashboard = async () => {
    // On a phone the drawer closes after every choice, so open it again before each click.
    if (await page.getByRole('button', { name: 'Toggle navigation' }).isVisible())
      await page.getByRole('button', { name: 'Toggle navigation' }).click();
    await page
      .getByRole('navigation', { name: 'Primary navigation' })
      .getByRole('button', { name: 'Dashboard' })
      .click();
  };
  const messages: string[] = [];
  page.once('dialog', (d) => {
    messages.push(d.message());
    void d.dismiss();
  });
  await toDashboard();
  await expect.poll(() => messages.length).toBe(1);
  expect(messages[0]).toMatch(/glossary/i);
  expect(new URL(page.url()).hash).toBe('#/glossary');
  await expect(page.getByLabel('New term')).toHaveValue('Half typed');

  page.once('dialog', (d) => void d.accept());
  await toDashboard();
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
  expect(new URL(page.url()).hash).toBe('#/dashboard');
});

test('an untouched glossary never asks before leaving', async ({ page }) => {
  await openGlossary(page);
  let asked = false;
  page.on('dialog', (d) => {
    asked = true;
    void d.dismiss();
  });
  if (await page.getByRole('button', { name: 'Toggle navigation' }).isVisible())
    await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page
    .getByRole('navigation', { name: 'Primary navigation' })
    .getByRole('button', { name: 'Dashboard' })
    .click();
  await expect(page.getByRole('heading', { name: 'Pipeline status' })).toBeVisible();
  expect(asked).toBe(false);
});

// --- the editor against the real server: list, add, edit, delete with confirm --------------------------------

const row = (page: Page, term: string) => page.getByRole('row', { name: new RegExp(term) });

test.describe('glossary editor on the fixture server', () => {
  test.beforeEach(async ({ request }) => reset(request));

  test('lists the deployed shows and the three sections', async ({ page }) => {
    await openGlossary(page);
    const options = await page.getByLabel('Show', { exact: true }).locator('option').allTextContents();
    expect(options).toEqual(['Neon Harbor', 'Paper Moon']);
    for (const tab of ['Names', 'Phrases', 'Hard fixes'])
      await expect(page.getByRole('button', { name: tab, exact: true })).toBeVisible();
    await expect(page.getByText('No terms match.')).toBeVisible();
  });

  test('adds a name, edits it, and the saved list shows each change', async ({ page }) => {
    await openGlossary(page);
    await add(page, 'Nami');
    await expect(page.locator('.notice.success').first()).toContainText(/Saved/);
    await expect(row(page, 'Nami')).toBeVisible();

    await row(page, 'Nami').getByRole('button', { name: 'Edit' }).click();
    await page.getByLabel('Term', { exact: true }).fill('Nami-swan');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(row(page, 'Nami-swan')).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Nami', exact: true })).toHaveCount(0);
  });

  test('adds and edits a hard fix, which stays a literal replacement', async ({ page }) => {
    await openGlossary(page);
    await page.getByRole('button', { name: 'Hard fixes' }).click();
    await page.getByLabel('New term').fill('acdc band');
    await page.locator('#glossary-new-value').fill('AC\\DC');
    await page.getByRole('button', { name: 'Add term' }).click();
    await expect(row(page, 'acdc band')).toContainText('AC\\DC');

    await row(page, 'acdc band').getByRole('button', { name: 'Edit' }).click();
    await page.locator('#glossary-edit-0').fill('AC/DC');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(row(page, 'acdc band')).toContainText('AC/DC');
  });

  test('delete asks first: declining keeps the term, accepting removes it', async ({ page }) => {
    await openGlossary(page);
    await add(page, 'Sanji');
    await expect(row(page, 'Sanji')).toBeVisible();

    let message = '';
    page.once('dialog', (d) => {
      message = d.message();
      void d.dismiss();
    });
    await row(page, 'Sanji').getByRole('button', { name: 'Delete' }).click();
    await expect.poll(() => message).toMatch(/Delete "Sanji"/);
    await expect(row(page, 'Sanji')).toBeVisible();

    page.once('dialog', (d) => void d.accept());
    await row(page, 'Sanji').getByRole('button', { name: 'Delete' }).click();
    await expect(row(page, 'Sanji')).toHaveCount(0);
  });

  test('a duplicate term is refused by the server and read as an invalid request', async ({ page }) => {
    await openGlossary(page);
    await add(page, 'Zoro');
    await expect(row(page, 'Zoro')).toBeVisible();
    await add(page, 'Zoro');
    await expect(page.getByRole('alert')).toContainText(/Invalid request: term already exists/);
  });

  test('the glossary editor has no accessibility violations', async ({ page }) => {
    await openGlossary(page);
    await add(page, 'Usopp');
    await expect(row(page, 'Usopp')).toBeVisible();
    await expectNoAxeViolations(page);
  });
});

// --- the form survives a refused save, focus never drops to the page body, odd files still render ------------

test.describe('glossary form keeps the operator in place', () => {
  test.beforeEach(async ({ request }) => reset(request));

  test('a 409 keeps the typed text and keeps focus inside the editor', async ({ page }) => {
    await openGlossary(page);
    await page.route('**/api/glossary', (route) =>
      route.request().method() === 'POST'
        ? route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'version conflict', version: 'abc' }),
          })
        : route.continue(),
    );
    await add(page, 'Nami');
    await expect(page.getByRole('alert')).toContainText(/conflict/i);
    await expect(page.getByLabel('New term')).toHaveValue('Nami');
    const focusInEditor = await page.evaluate(
      () => !!document.activeElement?.closest('[aria-label="Glossary editor"]'),
    );
    expect(focusInEditor, 'focus must not fall back to <body>').toBe(true);
  });

  test('after a successful add, focus returns to the New term field, emptied for the next one', async ({
    page,
  }) => {
    await openGlossary(page);
    await add(page, 'Brook');
    await expect(row(page, 'Brook')).toBeVisible();
    await expect(page.getByLabel('New term')).toBeFocused();
    await expect(page.getByLabel('New term')).toHaveValue('');
    await page.keyboard.type('Franky');
    await page.keyboard.press('Enter');
    await expect(row(page, 'Franky')).toBeVisible();
  });

  test('a file with a repeated name still renders every row and raises no page error', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.route(/\/api\/glossary\?show=/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          show: 'Neon Harbor',
          version: 'v',
          names: ['Luffy', 'Luffy', 'Zoro'],
          phrases: [],
          hard_fixes: {},
        }),
      }),
    );
    await openGlossary(page);
    await expect(page.getByRole('cell', { name: 'Luffy', exact: true })).toHaveCount(2);
    await expect(page.getByRole('cell', { name: 'Zoro', exact: true })).toHaveCount(1);
    expect(errors).toEqual([]);
  });
});

test('an admin tests and saves the wiki override, and the page shows the saved value', async ({ page }) => {
  let wiki = '';
  let posted: Record<string, unknown> | null = null;
  const detail = () => ({ show: 'Neon Harbor', version: 'v1', names: [], phrases: [], hard_fixes: {}, wiki });
  await page.route(/\/api\/glossary\?show=/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail()) }),
  );
  await page.route('**/api/glossary/wiki-test', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        api: 'https://yugioh.fandom.com/api.php',
        sitename: 'Yu-Gi-Oh! Wiki',
      }),
    }),
  );
  await page.route('**/api/glossary', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    posted = route.request().postDataJSON();
    wiki = String(posted?.wiki ?? '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, version: 'v2', reapply_hint: true }),
    });
  });
  await openGlossary(page);
  const field = page.getByLabel('Wiki', { exact: true });
  await expect(field).toHaveValue('');
  await expect(
    page.getByText('Fandom or MediaWiki site URL, e.g. https://yugioh.fandom.com. Empty = auto-detect.'),
  ).toBeVisible();
  await field.fill('https://yugioh.fandom.com');
  await page.getByRole('button', { name: 'Test wiki' }).click();
  await expect(page.getByText('Yu-Gi-Oh! Wiki')).toBeVisible();
  await page.getByLabel('New term').fill('Half typed');
  await page.getByRole('button', { name: 'Save wiki' }).click();
  await expect(page.locator('.notice.success').first()).toBeVisible();
  expect(posted).toEqual({ show: 'Neon Harbor', expected_version: 'v1', wiki: 'https://yugioh.fandom.com' });
  await expect(field).toHaveValue('https://yugioh.fandom.com');
  await expect(page.getByLabel('New term')).toHaveValue('Half typed'); // a wiki save keeps the term form
});

test('a non-admin sees the wiki as text with no Test or Save', async ({ page, request }) => {
  await reset(request);
  const made = await request.post('/api/users', {
    headers: { 'X-Api-Key': API_KEY },
    data: { username: 'viewer', password: 'viewer password!', role: 'user' },
  });
  expect([201, 409]).toContain(made.status());
  await page.goto('/review#/glossary');
  await signIn(page, 'viewer', 'viewer password!');
  await expect(page.getByLabel('New term')).toBeVisible();
  await expect(page.getByText('Wiki', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Wiki', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Test wiki' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save wiki' })).toHaveCount(0);
});
