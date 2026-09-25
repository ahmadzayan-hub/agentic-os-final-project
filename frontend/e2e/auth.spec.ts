import { expect, test } from '@playwright/test'
import { composerInput, skipOnboarding } from './helpers'

// A second server instance with managed auth enabled, so the sign-in
// wall and authenticated operation are both exercised for real. The
// token is minted with the same secret the server verifies against,
// standing in for a completed provider round-trip (the provider itself
// is external and is not called by these tests).
const AUTH_PORT = 8124
const AUTH_BASE = `http://127.0.0.1:${AUTH_PORT}`

// HS256 JWT — {"sub":"e2e-user","agentic_os_role":"analyst"} signed with
// the test-only secret the auth server verifies against. Minted by
// server/auth.py's helper; not a credential for any real system.
const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  'eyJzdWIiOiJlMmUtdXNlciIsImV4cCI6Mjc4NjQwMTcwMywiYWdlbnRpY19vc19yb2xlIjoiYW5hbHlzdCJ9.' +
  'J_dVri2xv87fsz8tl31lIpFa9mlPuStl3HBUnpMuFr0'

test.describe('managed authentication', () => {
  test.skip(
    ({ baseURL }) => baseURL === AUTH_BASE,
    'runs against the dedicated auth server only',
  )

  test('unauthenticated visitors get the sign-in wall', async ({ page }) => {
    await skipOnboarding(page)
    await page.goto(AUTH_BASE)

    const signIn = page.getByRole('main', { name: 'Sign in' })
    await expect(signIn).toBeVisible()
    await expect(signIn).toContainText('Agentic OS never sees them')
    // The workspace must not be reachable without credentials.
    await expect(page.getByRole('textbox', { name: 'Message' })).toHaveCount(0)
  })

  test('the sign-in form is keyboard operable and labelled', async ({ page }) => {
    await skipOnboarding(page)
    await page.goto(AUTH_BASE)
    await page.getByLabel('Email').focus()
    await page.keyboard.type('analyst@example.com')
    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Password')).toBeFocused()
  })

  /** The identity chip lives in the sidebar, which is a drawer on mobile. */
  async function revealIdentity(page: import('@playwright/test').Page) {
    const menu = page.getByRole('button', { name: 'Open navigation' })
    if (await menu.isVisible()) await menu.click()
  }

  test('a valid token unlocks the workspace and shows the role', async ({ page }) => {
    await skipOnboarding(page)
    await page.addInitScript((token) => {
      localStorage.setItem('aos-token', token)
    }, TOKEN)
    await page.goto(AUTH_BASE)

    await expect(composerInput(page)).toBeVisible()
    // The signed-in principal and its role come from the server.
    await revealIdentity(page)
    await expect(page.locator('.sidebar__meta').first()).toContainText('analyst')
  })

  test('signing out clears the session and returns to the wall', async ({ page }) => {
    await skipOnboarding(page)
    await page.addInitScript((token) => {
      localStorage.setItem('aos-token', token)
    }, TOKEN)
    await page.goto(AUTH_BASE)
    await expect(composerInput(page)).toBeVisible()

    await revealIdentity(page)
    await page.getByRole('button', { name: 'Sign out' }).first().click()

    await expect(page.getByRole('main', { name: 'Sign in' })).toBeVisible()
    const stored = await page.evaluate(() => localStorage.getItem('aos-token'))
    expect(stored).toBeNull()
  })

  test('an invalid token is rejected and never unlocks the workspace', async ({ page }) => {
    await skipOnboarding(page)
    await page.addInitScript(() => {
      localStorage.setItem('aos-token', 'forged.token.value')
    })
    await page.goto(AUTH_BASE)

    await expect(page.getByRole('main', { name: 'Sign in' })).toBeVisible()
    const stored = await page.evaluate(() => localStorage.getItem('aos-token'))
    expect(stored).toBeNull()
  })
})
