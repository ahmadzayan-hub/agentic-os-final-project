import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

// Dashboard pages (ADR 0032) over the bundled sample's cleaned table: 72
// records, months, two regions and three categories. Every page is
// checked with axe and for sideways scrolling at desktop and phone
// widths; a filter survives a reload; a group drills down to its rows;
// and the pages read in Arabic.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

async function finishedRun(request: APIRequestContext, goal: string) {
  let run = await (await request.post('/api/runs', { data: { goal } })).json()
  for (let step = 0; step < 80 && ['queued', 'running'].includes(run.state); step += 1) {
    run = await (await request.post(`/api/runs/${run.id}/advance`)).json()
  }
  expect(run.state).toBe('awaiting_approval')
  return run.id as string
}

async function expectNoViolations(page: Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  expect(
    results.violations,
    `${context}: ${results.violations.map((v) => `${v.id} (${v.nodes.length})`).join(', ')}`,
  ).toEqual([])
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}

async function openDashboard(page: Page, runId: string, rest = '') {
  await page.goto(`/#/dashboard/${runId}${rest}`)
  await page.locator('.viewload').waitFor({ state: 'detached' })
  await expect(page.locator('.dash-coverage')).toContainText('records')
}

test('every page of the dashboard, accessible and without sideways scrolling', async ({ page }) => {
  await skipOnboarding(page)
  const runId = await finishedRun(page.request, 'Dashboard pages')
  await openDashboard(page, runId)
  await expect(page.getByRole('heading', { name: 'Dashboard pages' })).toBeVisible()
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 72 of 72 records.')
  await expect(page.locator('.kpi').first()).toContainText('72')
  await expect(page.locator('.kpi').nth(3)).toContainText('North')

  const pages = page.getByRole('navigation', { name: 'Dashboard pages' })
  for (const name of ['Overview', 'Breakdown', 'Trend', 'Distribution', 'Relationship', 'Records']) {
    await pages.getByRole('link', { name }).click()
    await expect(pages.getByRole('link', { name })).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('.dash-page [role="status"].skeleton')).toHaveCount(0)
    await expectNoViolations(page, `${name} page`)
    expect(await horizontalOverflow(page), `${name} page scrolls sideways`).toBeLessThanOrEqual(0)
  }
  // The records page holds the rows, 25 at a time.
  await expect(page.getByText('Rows 1–25 of 72')).toBeVisible()
  await page.getByRole('button', { name: 'Next page' }).click()
  await expect(page.getByText('Rows 26–50 of 72')).toBeVisible()
})

test('a filter survives a reload and a group drills down to its records', async ({ page }) => {
  await skipOnboarding(page)
  const runId = await finishedRun(page.request, 'Dashboard drill-down')
  await openDashboard(page, runId, '/breakdown')
  await page.getByLabel('Break down by').selectOption('category')
  const table = page.locator('.dash-page table')
  await expect(table).toContainText('Software')
  await page.getByRole('button', { name: 'Show the records for Software' }).click()

  await expect(page.getByRole('link', { name: 'Records' })).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 24 of 72 records.')
  await expect(page.getByText('Rows 1–24 of 24')).toBeVisible()
  expect(page.url()).toContain('f.category=Software')

  await page.reload()
  await page.locator('.viewload').waitFor({ state: 'detached' })
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 24 of 72 records.')
  await expect(page.getByRole('link', { name: 'Records' })).toHaveAttribute('aria-current', 'page')

  // The filter holds on every page, then clears in one step.
  await page.getByRole('link', { name: 'Overview' }).click()
  await expect(page.locator('.kpi').first()).toContainText('24')
  await page.getByRole('button', { name: 'Clear filters (1)' }).click()
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 72 of 72 records.')

  // A period range from the filter bar.
  await page.getByLabel('From').selectOption('2025-11')
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 12 of 72 records.')
})

test('the dashboard in Arabic', async ({ page }) => {
  await skipOnboarding(page)
  await page.addInitScript(() => localStorage.setItem('aos-locale', 'ar'))
  const runId = await finishedRun(page.request, 'لوحة بالعربية')
  await page.goto(`/#/dashboard/${runId}/breakdown`)
  await page.locator('.viewload').waitFor({ state: 'detached' })
  await expect(page.locator('.dash-coverage')).toHaveText('يُعرض 72 من أصل 72 سجلاً.')
  await expect(page.getByRole('navigation', { name: 'صفحات لوحة المعلومات' })).toBeVisible()
  await expect(page.getByLabel('التقسيم حسب')).toBeVisible()
  await expectNoViolations(page, 'Arabic breakdown')
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0)
})

test('a finished analysis opens its dashboard, and the picker lists it', async ({ page }) => {
  await skipOnboarding(page)
  const runId = await finishedRun(page.request, 'Dashboard entry points')
  await page.goto(`/#/runs/${runId}`)
  await page.locator('.viewload').waitFor({ state: 'detached' })
  await page.getByRole('button', { name: 'Open dashboard' }).click()
  await expect(page).toHaveURL(new RegExp(`#/dashboard/${runId}`))
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 72 of 72 records.')
  await page.getByRole('button', { name: 'Another analysis' }).click()
  // Both viewports share one database, so this goal may be listed twice.
  await expect(page.getByRole('button', { name: /Dashboard entry points/ }).first()).toBeVisible()
  await expectNoViolations(page, 'dashboard picker')
  await openTab(page, /^Dashboards/)
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
})
