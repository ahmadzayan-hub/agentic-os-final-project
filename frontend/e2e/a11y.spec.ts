import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { openTab, sendMessage, skipOnboarding } from './helpers'

// Scanning with reduced motion enabled avoids analyzing dialogs mid-fade
// (axe would read blended colors) and exercises the app's
// prefers-reduced-motion support at the same time.
test.use({ contextOptions: { reducedMotion: 'reduce' } })

// Automated WCAG 2.x A/AA scan of every view and the dialogs. Automated
// checks complement — not replace — the manual keyboard review recorded in
// docs/UI_UX_AUDIT.md.
async function expectNoViolations(page: import('@playwright/test').Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  expect(
    results.violations,
    `${context}: ${results.violations.map((v) => `${v.id} (${v.nodes.length})`).join(', ')}`,
  ).toEqual([])
}

test('all views and dialogs pass automated WCAG 2.2 AA checks', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')

  await sendMessage(page, 'Hello there')
  await page.locator('.msg--agent .msg__bubble').last().waitFor()
  await expectNoViolations(page, 'chat view')

  await openTab(page, /^Memory/)
  await expectNoViolations(page, 'memory view')

  await openTab(page, /^Preferences/)
  await expectNoViolations(page, 'preferences view')

  await openTab(page, /^Activity/)
  await expectNoViolations(page, 'activity view')

  // The Runs view is the most complex screen in the app — approval card,
  // charts, and the analytics-type tablist — so it is scanned in the
  // state that has all of them on screen at once.
  await openTab(page, /^Runs/)
  await expectNoViolations(page, 'runs view (setup)')
  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })
  await expectNoViolations(page, 'runs view (approval, charts, reports)')

  await page.keyboard.press('ControlOrMeta+k')
  await page.getByRole('dialog', { name: 'Command palette' }).waitFor()
  await expectNoViolations(page, 'command palette')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Help and commands' }).click()
  await page.getByRole('dialog', { name: 'Commands' }).waitFor()
  await expectNoViolations(page, 'help dialog')
})

test('onboarding dialog passes automated WCAG 2.2 AA checks', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('dialog', { name: 'Welcome to Agentic OS' }).waitFor()
  await expectNoViolations(page, 'onboarding dialog')
})
