import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { composerInput, openTab, skipOnboarding } from './helpers'

test.use({ contextOptions: { reducedMotion: 'reduce' } })

test('a late start response preserves the destination and the durable run', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/#/runs')
  let release!: () => void
  let received!: () => void
  let createdId = ''
  const ready = new Promise<void>((resolve) => { received = resolve })
  const held = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return }
    const response = await route.fetch()
    createdId = (await response.json()).id
    received()
    await held
    await route.fulfill({ response })
  })
  await page.getByRole('button', { name: 'Start run', exact: true }).click()
  await ready
  await openTab(page, /^Datasets/)
  release()
  await expect(page.locator('section[aria-label="Runs"] button[type="submit"]')).toBeEnabled()
  await expect(page).toHaveURL(/#\/datasets$/)
  await expect(page.getByRole('heading', { name: 'Datasets', exact: true })).toBeVisible()
  await page.goto(`/#/runs/${createdId}`)
  await expect(page.getByRole('region', { name: 'Run detail' })).toBeVisible()
})

test('drafts, deep links, evidence and exact-report keyboard approval', async ({ page }, testInfo) => {
  await skipOnboarding(page)
  await page.goto('/')
  await composerInput(page).fill('Keep my unsent question')
  await openTab(page, /^Datasets/)
  await openTab(page, /^Workspace/)
  await expect(composerInput(page)).toHaveValue('Keep my unsent question')
  await page.reload()
  await expect(composerInput(page)).toHaveValue('Keep my unsent question')

  await openTab(page, /^Runs/)
  await page.getByLabel('Goal').fill('Find what changed in sample sales')
  await page.reload()
  await expect(page.getByLabel('Goal')).toHaveValue('Find what changed in sample sales')
  await page.getByRole('button', { name: 'Start run', exact: true }).click()
  await expect(page).toHaveURL(/#\/runs\/[a-z0-9]+$/)
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({ timeout: 40_000 })
  const linked = page.url()
  // A skip action moves focus without replacing the analysis route.
  await page.locator('.skiplink').evaluate((element: HTMLAnchorElement) => element.click())
  await expect(page).toHaveURL(linked)
  await expect(page.locator('#workspace-main')).toBeFocused()
  await page.reload()
  await expect(page.locator('.cockpit__finding')).toContainText('45%')

  await page.getByRole('button', { name: /^Why is this true\?/ }).first().click()
  const evidence = page.getByRole('dialog', { name: 'Why is this true?' })
  await expect(evidence.getByRole('heading', { name: 'Why is this true?' })).toBeInViewport()
  await expect(evidence).toBeFocused()
  await expect(evidence).toContainText('c_change')
  await expect(evidence.getByRole('table')).toBeVisible()
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze()).violations).toEqual([])
  await page.screenshot({ path: `../docs/screenshots/${testInfo.project.name}-evidence.png` })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: /^Why is this true\?/ }).first()).toBeFocused()

  await openTab(page, /^Approvals/)
  const card = page.locator('.approval-inbox > .card').filter({ hasText: 'Find what changed in sample sales' })
  await card.getByRole('button', { name: 'Review', exact: true }).focus()
  await page.keyboard.press('Enter')
  await card.locator('.decision__preview > summary').focus()
  await page.keyboard.press('Enter')
  await expect(card.locator('pre')).toContainText('Every claim in this report')
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze()).violations).toEqual([])
  await page.screenshot({ path: `../docs/screenshots/${testInfo.project.name}-approvals.png` })
  const approve = card.getByRole('button', { name: 'Approve and publish', exact: true })
  // Continue from the preview using only Tab, then activate the decision.
  for (let moves = 0; moves < 12 && !(await approve.evaluate((element) => element === document.activeElement)); moves += 1) {
    await page.keyboard.press('Tab')
  }
  await expect(approve).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('status').filter({ hasText: 'Publication confirmed' })).toBeVisible()
  await page.goto(linked)
  await expect(page.locator('.privacy-note').filter({ hasText: 'Reports/' })).toBeVisible()
  await page.getByRole('button', { name: 'Read the published report', exact: true }).click()
  await expect(page.locator('.runreport--full')).toBeFocused()
})

test('Arabic phone cockpit and evidence fit the viewport', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'explicit phone sizes run once')
  await skipOnboarding(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Change language' }).click()
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
  await page.goto('/#/runs')
  await page.getByRole('button', { name: 'بدء التحليل', exact: true }).click()
  await expect(page.getByRole('region', { name: 'موافقة مطلوبة' })).toBeVisible({ timeout: 40_000 })
  for (const button of await page.getByRole('button').all()) {
    const bounds = await button.boundingBox()
    expect(bounds?.width).toBeGreaterThanOrEqual(44)
    expect(bounds?.height).toBeGreaterThanOrEqual(44)
  }
  await page.screenshot({ path: '../docs/screenshots/phone-390-arabic-cockpit.png' })
  await page.getByRole('button', { name: /^ما الدليل على ذلك؟/ }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('table')).toBeVisible()
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
    const bounds = await dialog.boundingBox()
    expect(bounds?.height).toBeLessThanOrEqual(812)
  }
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze()).violations).toEqual([])
  await page.keyboard.press('Escape')
})
