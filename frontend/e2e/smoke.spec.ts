import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const BOOTSTRAP_TOKEN = process.env.ADMIN_BOOTSTRAP_TOKEN || ''
const ADMIN = { username: 'admin', password: 'admin-ui-smoke-pass' }
// Some headless Chrome builds never fire requestAnimationFrame, which stalls Playwright's
// "stable" actionability check; forcing skips only that wait.
const CLICK = { force: true }
const ALICE = { username: 'alice', password: 'alice-ui-smoke-pass' }

async function token(request: APIRequestContext, creds: { username: string; password: string }): Promise<string> {
  const response = await request.post('/api/v1/auth/token', { form: creds })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).access_token
}

async function signIn(page: Page, creds: { username: string; password: string }) {
  await page.goto('/app/login')
  await page.getByLabel('Username').fill(creds.username)
  await page.getByLabel('Password').fill(creds.password)
  await page.getByLabel('Password').press('Enter')
  await expect(page.getByRole('link', { name: 'Targets' })).toBeVisible()
}

test.beforeAll(async ({ request }) => {
  const boot = await request.post('/api/v1/auth/bootstrap', {
    data: { ...ADMIN, bootstrap_token: BOOTSTRAP_TOKEN },
  })
  expect([200, 201]).toContain(boot.status())
  const admin = { Authorization: `Bearer ${await token(request, ADMIN)}` }
  const user = await request.post('/api/v1/auth/users', {
    headers: admin,
    data: { ...ALICE, roles: ['user'] },
  })
  expect(user.ok()).toBeTruthy()
  const target = await request.post('/api/v1/targets', { headers: admin, data: { name: 'UI-BOARD' } })
  expect(target.ok()).toBeTruthy()
})

test('user reserves and releases a target', async ({ page }) => {
  await signIn(page, ALICE)
  await expect(page.getByRole('link', { name: 'Admin' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Reserve' }).click(CLICK)
  await page.getByRole('button', { name: 'Confirm' }).click(CLICK)
  await expect(page.getByText(/Reserved by alice/)).toBeVisible()

  await page.getByRole('link', { name: 'Reservations' }).click(CLICK)
  await expect(page.getByText('UI-BOARD')).toBeVisible()

  await page.getByRole('link', { name: 'Targets' }).click(CLICK)
  await page.getByRole('button', { name: 'Release' }).click(CLICK)
  await expect(page.getByText('No active reservation')).toBeVisible()
})

test('non-admin cannot open the admin area', async ({ page }) => {
  await signIn(page, ALICE)
  await page.goto('/app/admin')
  await expect(page.getByText('403 Forbidden')).toBeVisible()
})

test('admin creates an agent enrollment and sees a checksum-verified install command', async ({ page }) => {
  await signIn(page, ADMIN)
  await page.getByRole('link', { name: 'Admin' }).click(CLICK)
  await page.getByRole('button', { name: 'Agents' }).click(CLICK)
  await page.getByPlaceholder('Agent name').fill('ui-smoke-pi')
  await page.getByRole('button', { name: 'Create Enrollment' }).click(CLICK)
  await expect(page.locator('pre.log-console')).toContainText('sha256sum -c')
})
