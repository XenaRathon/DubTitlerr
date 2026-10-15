import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('human review workspace keeps real workflow semantics', async ({ page, request }, testInfo) => {
  // One long journey: three axe scans, audio extraction and a full-page screenshot take 20-26 s on a quiet
  // machine and 36-40 s when other workers load it. No fixed waits are involved, so give it room instead of
  // slimming the journey; the global 30 s default stays for every other spec.
  test.setTimeout(90_000);
  const reset = await request.post('/__test/reset', {
    headers: { 'X-Api-Key': 'browser-fixture-token' },
  });
  expect(reset.ok()).toBe(true);
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await page.goto('/review');
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
  const loginAccessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(loginAccessibility.violations).toEqual([]);
  // The fixture server imported a username and password as its first admin: the sign-in form is all there is.
  await expect(page.getByLabel('Username')).toBeVisible();
  await expect(page.getByLabel('Password')).toHaveAttribute('type', 'password');
  await expect(page.getByLabel('Password')).toHaveAttribute('autocomplete', 'current-password');
  await expect(page.getByLabel('Access token')).toHaveCount(0);
  await expect(page.getByText('Make every')).toHaveCount(0);
  await page.getByLabel('Username').fill('reviewer');
  await page.getByLabel('Password').fill('not-the-password');
  await page.getByLabel('Password').press('Enter');
  await expect(page.getByRole('alert')).toContainText('wrong username or password');
  await page.getByLabel('Password').fill('browser-fixture-password');
  await page.getByLabel('Password').press('Enter');
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  await expect(page.getByLabel('Search episodes')).toBeVisible();
  await page.getByLabel('Search episodes').fill('Neon Harbor');
  await page.getByRole('button', { name: /Neon Harbor.*S01E01/ }).click();
  await expect(page.getByTestId('evidence')).toBeVisible();
  await page.getByLabel('Search review lines').fill('factory');
  await expect(page.locator('del')).toContainText('factory');
  await expect(page.locator('ins')).toContainText('needle');
  await page.getByRole('button', { name: /Listen to dub/ }).click();
  await expect(page.getByLabel('English dub preview')).toBeVisible();
  await expect
    .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.readyState))
    .toBeGreaterThan(0);
  await page.getByRole('button', { name: /Write correction/ }).click();
  await page.getByLabel('Corrected subtitle').fill('We are looking for the factory.');
  const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('review-workspace.png'), fullPage: true });
  await page.getByLabel('Search review lines').fill('blue');
  await expect(page.getByLabel('English dub preview')).toHaveCount(0);
  await page.getByLabel('Search review lines').fill('factory');
  await expect(page.getByLabel('Corrected subtitle')).toHaveValue('We are looking for the factory.');
  // Failed requests keep the staged edit intact and restore the Save button.
  await page.route('**/api/decide', (route) => route.abort('failed'));
  await page.getByRole('button', { name: /Save 1 choice/ }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('Corrected subtitle')).toHaveValue('We are looking for the factory.');
  await expect(page.getByRole('button', { name: /Save 1 choice/ })).toBeEnabled();
  await page.unroute('**/api/decide');
  await page.getByRole('button', { name: /Save 1 choice/ }).click();
  await expect(page.getByRole('status')).toContainText('1 choice saved');
  await expect(page.getByRole('status')).toContainText('media was not rewritten');
  await page.getByLabel('Search review lines').fill('');
  // Keyboard review must work, and must not fire while typing.
  await page.locator('h1').click();
  await page.keyboard.press('r');
  // A staged verdict advances to the next line that has no choice yet.
  await expect(page.getByRole('button', { name: 'Review line 1, staged', exact: true })).toBeVisible();
  await expect(page.getByTestId('evidence')).toContainText(/Line 2 of \d+/);
  await expect(page.getByRole('button', { name: /Keep original/ })).toHaveAttribute('aria-pressed', 'false');
  await page.keyboard.press('k');
  await expect(page.getByRole('button', { name: /Keep original/ })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Clear choice' }).click();
  // Staging two lines and a partial refusal must preserve only the unsaved question.
  const rows = await page.request.get(
    '/api/episode?stem=' +
      encodeURIComponent(
        (
          await (
            await page.request.get('/api/episodes', {
              headers: { 'X-Api-Key': 'browser-fixture-token' },
            })
          ).json()
        ).episodes.find((ep: { name: string }) => ep.name.includes('S01E01')).stem,
      ),
    { headers: { 'X-Api-Key': 'browser-fixture-token' } },
  );
  expect((await rows.json()).entries.length).toBeGreaterThan(1);
  await page.getByRole('button', { name: 'Review line 1', exact: true }).click();
  await page.getByRole('button', { name: /Keep original/ }).click();
  await page.getByRole('button', { name: 'Review line 3', exact: true }).click();
  await page.getByRole('button', { name: /Keep original/ }).click();
  await page.route('**/api/decide', async (route) => {
    const body = route.request().postDataJSON();
    const rejected = body.decisions[1];
    const response = await route.fetch({
      postData: JSON.stringify({ ...body, decisions: [body.decisions[0]] }),
    });
    const data = await response.json();
    await route.fulfill({
      json: { ...data, errors: [{ index: rejected.index, error: 'Test partial refusal: retry this line' }] },
    });
  });
  await page.getByRole('button', { name: /Save 2 choices/ }).click();
  await expect(page.getByRole('status')).toContainText('1 choice saved');
  await expect(page.getByRole('alert')).toContainText('Test partial refusal');
  await expect(page.getByRole('button', { name: /Save 1 choice/ })).toBeEnabled();
  await page.unroute('**/api/decide');
  await page.getByRole('button', { name: /Save 1 choice/ }).click();
  await expect(page.getByRole('button', { name: /Save.*choices/ })).toBeDisabled();
  await page.getByLabel('Search review lines').fill('r');
  await expect(page.getByRole('button', { name: /Save.*choices/ })).toBeDisabled();
  await page.getByLabel('Search review lines').fill('');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Apply saved decisions' }).click();
  await expect(page.getByRole('status')).toContainText('subtitles rebuilt and remux queued');
  await page.getByRole('button', { name: 'Keyboard shortcuts', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();

  async function nav(name: string | RegExp) {
    if (testInfo.project.name === 'mobile')
      await page.getByRole('button', { name: 'Toggle navigation' }).click();
    await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name }).click();
  }
  await nav('Shared lines');
  await expect(page.getByRole('heading', { name: 'Shared lines', level: 1 })).toBeVisible();
  await expect(page.getByTestId('evidence')).toContainText('2 episodes');
  await page.getByRole('button', { name: /Keep repair/ }).click();
  await page.getByRole('button', { name: /Save 1 choice/ }).click();
  await expect(page.getByRole('status')).toContainText('1 choice saved');
  await nav(/Review inbox/);
  // The last remaining episode question was settled in Shared lines; the inbox must re-fetch it.
  await expect(page.getByRole('heading', { name: 'This queue is clear.' })).toBeVisible();
  await page.getByLabel('Search episodes').fill('Paper Moon');
  await page.getByRole('button', { name: /Paper Moon.*S02E03/ }).click();
  await page.getByLabel('Search review lines').fill('script');
  await expect(page.getByTestId('evidence')).toContainText('<script>bad</script>');
  await expect(page.locator('.evidence img')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Open your review workspace' })).toBeVisible();
  // Signing in again opens the same workspace, and no token was ever put in storage.
  await page.getByLabel('Username').fill('reviewer');
  await page.getByLabel('Password').fill('browser-fixture-password');
  const passwordAccessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(passwordAccessibility.violations).toEqual([]);
  await page.getByLabel('Password').press('Enter');
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.length + localStorage.length)).toBe(0);
});
