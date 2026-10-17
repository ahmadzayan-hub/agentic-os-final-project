import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

// Column mapping in the browser (ADR 0025): a file is added, the server
// suggests what each column is, the owner changes one choice and saves,
// a refused mapping is explained field by field, and a run follows the
// saved mapping. In English and Arabic, at desktop and phone widths.
//
// The database is shared by every spec and both viewports, so this table
// is used here alone, and each test starts by clearing any mapping an
// earlier run of the spec saved.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

const NAME = 'branch-takings.csv'
// Day-first dates across a year end, money with signs, a counting ID, a
// numbered store code and free-text remarks: what real exports look like.
const ROWS = [
  ['1', '15/11/2024', '3', 'Riverside', '$1,200', 'opening week'],
  ['2', '20/11/2024', '1', 'Harbour', '$800', 'quiet'],
  ['3', '05/12/2024', '3', 'Riverside', '$1,500', 'gift season'],
  ['4', '18/12/2024', '2', 'Harbour', '(200)', 'refund'],
  ['5', '09/01/2025', '1', 'Riverside', '$1,100', 'new staff'],
  ['6', '22/01/2025', '2', 'Harbour', '$950', 'late stock'],
  ['7', '03/02/2025', '3', 'Riverside', '$1,300', 'bulk order'],
  ['8', '14/02/2025', '1', 'Harbour', '$1,050', 'valentine'],
  ['9', '28/02/2025', '2', 'Riverside', '$1,250', 'cash only'],
  ['10', '13/03/2025', '3', 'Harbour', '$1,400', 'online'],
  ['11', '27/03/2025', '2', 'Riverside', '$1,000', 'promo'],
]
const CSV =
  'row_id,order_date,store_code,branch,takings,remarks\n' +
  ROWS.map((row) => row.map((v) => (v.includes(',') ? `"${v}"` : v)).join(',')).join('\n') +
  '\n'

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

/** Add the table and wait for its columns to open, unmapped. */
async function openColumns(page: Page, addLabel = 'Add a dataset', clearLabel = 'Use automatic detection') {
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: addLabel }).first().click()
  await (await chooser).setFiles({ name: NAME, mimeType: 'text/csv', buffer: Buffer.from(CSV) })
  const panel = page.locator('section.mapping')
  await expect(panel.locator('select').first()).toBeVisible()
  const clear = panel.getByRole('button', { name: clearLabel })
  if (await clear.isVisible()) {
    await clear.click()
    await expect(clear).toHaveCount(0)
  }
  return panel
}

test('the suggested columns are adjusted, saved and followed by a run', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Datasets/)
  const panel = await openColumns(page)

  await expect(panel.getByRole('heading', { name: `Columns of ${NAME}` })).toBeVisible()
  await expect(panel.getByRole('region', { name: `First rows of ${NAME}` })).toContainText('$1,200')
  // The suggestion, each with its reason.
  await expect(panel.getByRole('combobox', { name: 'takings' })).toHaveValue('measure')
  await expect(panel.getByRole('combobox', { name: 'order_date' })).toHaveValue('date')
  await expect(panel.getByRole('combobox', { name: 'row_id' })).toHaveValue('ignore')
  await expect(panel.getByRole('combobox', { name: 'remarks' })).toHaveValue('ignore')
  await expect(panel.getByText('it looks like an identifier')).toBeVisible()
  await expect(panel.getByRole('combobox', { name: 'Breakdown' })).toHaveValue('store_code')
  await expectNoViolations(page, 'mapping panel with a suggestion')
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0)

  // Break down by branch rather than the store code, by month.
  await panel.getByRole('combobox', { name: 'Breakdown' }).selectOption('branch')
  await panel.getByRole('combobox', { name: 'Sum dates by' }).selectOption('month')
  await expect(panel.getByText('You have changes that are not saved yet.')).toBeVisible()
  await panel.getByRole('button', { name: 'Save mapping' }).click()
  await expect(panel.getByText('Mapping saved. Runs of this dataset now follow it.')).toBeVisible()
  await expect(page.locator('.dataset').filter({ hasText: NAME })).toContainText('Mapped')

  await panel.getByRole('button', { name: 'Analyse with this mapping' }).click()
  const picker = page.getByLabel('Choose a stored dataset')
  await expect(picker.locator('option:checked')).toContainText(`${NAME} · 11 data rows · CSV · Mapped`)
  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({ timeout: 40_000 })
  const disclosure = page.locator('.run-timeline__disclosure')
  if ((await disclosure.getAttribute('open')) === null) await disclosure.locator(':scope > summary').click()
  const tasks = page.locator('.pipeline__bands')
  await expect(tasks).toContainText('Measure “takings” (the owner\'s column mapping)')
  await expect(tasks).toContainText('grouped by “branch”, trended by “order_date” by month (column mapping)')
})

test('a refused mapping is summarised, and each problem leads to its field', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Datasets/)
  const panel = await openColumns(page)

  // Free text cannot be a measure, and the server says why, with counts.
  await panel.getByRole('combobox', { name: 'remarks' }).selectOption('measure')
  await panel.getByRole('combobox', { name: 'Measure analysed' }).selectOption('remarks')
  await panel.getByRole('button', { name: 'Save mapping' }).click()

  const summary = panel.getByRole('alert')
  await expect(summary).toBeFocused()
  await expect(summary).toContainText('There is a problem')
  await expect(summary).toContainText('“remarks” cannot be a measure: 0 of 11 filled cells are numbers.')
  const remarks = panel.getByRole('combobox', { name: 'remarks' })
  await expect(remarks).toHaveAttribute('aria-invalid', 'true')
  await summary.getByRole('link', { name: /“remarks” cannot be a measure/ }).click()
  await expect(remarks).toBeFocused()
  await expectNoViolations(page, 'mapping panel with errors')
  // Nothing was saved.
  await expect(page.locator('.dataset').filter({ hasText: NAME })).not.toContainText('Mapped')
})

test('the columns read right to left in Arabic, with the same checks', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('aos-locale', 'ar')
    localStorage.setItem('aos-onboarded', '1')
  })
  await page.goto('/')
  const menu = page.getByRole('button', { name: 'فتح قائمة التنقل' })
  const tab = page.getByRole('button', { name: /^مجموعات البيانات/ }).filter({ visible: true })
  await menu.or(tab.first()).first().waitFor()
  if (await menu.isVisible()) await menu.click()
  await tab.first().click()

  const panel = await openColumns(page, 'أضف مجموعة بيانات', 'استخدام الاكتشاف التلقائي')
  await expect(panel.getByRole('heading', { name: `أعمدة ${NAME}` })).toBeVisible()
  await expect(panel.getByText('رقم صحيح لا يتكرر في أي صف ويتزايد بانتظام: يبدو معرّفاً.')).toBeVisible()
  await expect(panel.getByRole('combobox', { name: 'takings' })).toHaveValue('measure')

  await panel.getByRole('combobox', { name: 'branch' }).selectOption('measure')
  await panel.getByRole('combobox', { name: 'المقياس المحلَّل' }).selectOption('branch')
  await panel.getByRole('button', { name: 'حفظ الربط' }).click()
  const summary = panel.getByRole('alert')
  await expect(summary).toContainText('توجد مشكلة')
  await expect(summary).toContainText('لا يصلح «branch» مقياساً')
  await expectNoViolations(page, 'Arabic mapping panel with errors')
  // The narrowest phone: the preview scrolls inside its frame, not the page.
  await page.setViewportSize({ width: 320, height: 720 })
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0)
})

