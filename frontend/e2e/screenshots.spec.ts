import { test } from '@playwright/test'
import { lastAgentBubble, openTab, sendMessage, skipOnboarding } from './helpers'

// Captures the final interface for the documentation. Runs last in file
// order but is independent of the other specs. Themes are stamped
// directly because the header toggle is hidden on narrow viewports.
// Reduced motion makes a theme change land at once, so no capture
// catches a colour halfway through its transition.
test.use({ contextOptions: { reducedMotion: 'reduce' } })

test('capture interface screenshots', async ({ page }, testInfo) => {
  await skipOnboarding(page)
  await page.goto('/')
  const shot = (name: string) =>
    page.screenshot({ path: `../docs/screenshots/${testInfo.project.name}-${name}.png` })
  // A view is ready to capture once its skeletons have been replaced.
  const settled = () =>
    page.waitForFunction(
      () => document.querySelector('main .panel__title') && !document.querySelector('main .skeleton'),
    )
  const theme = (value: string) =>
    page.evaluate((themeValue) => {
      document.documentElement.dataset.theme = themeValue
    }, value)

  await theme('dark')
  await page.getByText('What would you like to accomplish?').waitFor()
  await shot('hero-dark')

  await sendMessage(page, 'Hello! What can you do?')
  await lastAgentBubble(page).waitFor()
  await sendMessage(page, '/help')
  await lastAgentBubble(page).waitFor()

  await theme('light')
  await shot('chat-light')
  await theme('dark')
  await shot('chat-dark')

  if (testInfo.project.name === 'desktop') {
    await openTab(page, /^Memory/)
    await page.getByText('Data controls').waitFor()
    await shot('memory-dark')

    await openTab(page, /^Activity/)
    await page.getByText('Session health').waitFor()
    await shot('activity-dark')

    await openTab(page, /^Runs/)
    await page.getByRole('button', { name: 'Start run' }).click()
    await page
      .getByRole('region', { name: 'Approval required' })
      .waitFor({ timeout: 20_000 })
    await shot('runs-dark')

    // The same screens in Arabic, right-to-left, switched from the
    // header the way a reader would.
    await page.getByRole('button', { name: 'Change language' }).click()
    await page.getByRole('status').filter({ hasText: 'جاهز' }).waitFor()
    // A report keeps the language its run was started in, so the Arabic
    // screenshot starts an Arabic run (ADR 0022).
    await page.getByRole('button', { name: 'كل التحليلات' }).click()
    await page.getByRole('button', { name: 'بدء التحليل' }).click()
    await page.locator('pre.runreport--full[lang="ar"]').waitFor({ timeout: 20_000 })
    await page.getByRole('region', { name: 'موافقة مطلوبة' }).waitFor()
    await shot('runs-arabic-dark')

    await page.getByRole('button', { name: /^مساحة العمل/ }).first().click()
    await lastAgentBubble(page).waitFor()
    await shot('chat-arabic-dark')
    await theme('light')
    await shot('chat-arabic-light')

    // The Overview and Datasets views (ADR 0023), in Arabic and English.
    // The latest findings come from the Arabic run, and stay Arabic in
    // the English interface: a report keeps its language.
    await page.getByRole('button', { name: /^نظرة عامة/ }).first().click()
    await settled()
    await shot('overview-arabic-light')
    await page.getByRole('button', { name: 'تغيير اللغة' }).click()
    await page.getByRole('status').filter({ hasText: 'Ready' }).waitFor()
    await theme('dark')
    await settled()
    await shot('overview-dark')
    await theme('light')
    await shot('overview-light')
    await openTab(page, /^Datasets/)
    await settled()
    await theme('dark')
    await shot('datasets-dark')
  } else {
    await openTab(page, /^Overview/)
    await settled()
    await shot('overview-dark')
  }
})
