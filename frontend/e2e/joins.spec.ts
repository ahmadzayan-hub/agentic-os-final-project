import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

// Several datasets in one run (ADR 0030): a lookup is joined onto orders,
// the merge is previewed with its match counts, a lookup whose key
// repeats is refused, and a run starts with the merge stage in it. In
// English and Arabic, at desktop and phone widths.
//
// The database is shared by every spec and both viewports, so these
// tables are this spec's alone and "already stored" is expected.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

const ORDERS = 'e2e-orders.csv'
const CATALOGUE = 'e2e-catalogue.csv'
const DUPLICATED = 'e2e-catalogue-dupes.csv'
// Eight orders over four months; item K4 is not in the catalogue.
const ORDERS_CSV =
  'month,item,channel,amount\n' +
  [
    ['2025-01', 'K1', 'Web', 120], ['2025-01', 'K2', 'Store', 80],
    ['2025-02', 'K3', 'Web', 140], ['2025-02', 'K4', 'Store', 60],
    ['2025-03', 'K1', 'Store', 130], ['2025-03', 'K2', 'Web', 90],
    ['2025-04', 'K3', 'Store', 150], ['2025-04', 'K4', 'Web', 70],
  ].map((row) => row.join(',')).join('\n') + '\n'
const CATALOGUE_CSV = 'item,family,unit_cost\nK1,Tools,5\nK2,Paint,3\nK3,Tools,7\nK9,Garden,2\n'
const DUPLICATED_CSV = 'item,family\nK1,Tools\nK1,Paint\nK2,Paint\n'

async function store(page: Page, name: string, text: string) {
  const response = await page.request.post(`/api/datasets?name=${name}`, {
    data: Buffer.from(text),
    headers: { 'Content-Type': 'text/csv' },
  })
  expect([200, 201]).toContain(response.status())
  return (await response.json()).dataset.id as string
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

/** openTab, with the Arabic name of the phone's navigation button. */
async function openArabicTab(page: Page, name: RegExp) {
  const menu = page.getByRole('button', { name: 'فتح قائمة التنقل' })
  const target = page.getByRole('button', { name }).filter({ visible: true })
  await menu.or(target.first()).first().waitFor()
  if (await menu.isVisible()) await menu.click()
  await target.first().click()
  await page.locator('.viewload').waitFor({ state: 'detached' })
}

/** Store this spec's tables and reload, so the run form lists them. */
async function startFromOrders(page: Page) {
  const orders = await store(page, ORDERS, ORDERS_CSV)
  await store(page, CATALOGUE, CATALOGUE_CSV)
  await store(page, DUPLICATED, DUPLICATED_CSV)
  await page.reload()
  return orders
}

test('a lookup is joined, previewed and run', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  const orders = await startFromOrders(page)
  await openTab(page, /^Runs/)
  await page.getByRole('button', { name: 'Stored dataset' }).click()
  await page.getByLabel('Choose a stored dataset').selectOption(orders)

  const builder = page.getByRole('group', { name: 'Join other datasets (optional)' })
  await builder.getByRole('button', { name: 'Join a dataset' }).click()
  const join = builder.getByRole('group', { name: 'Join 1' })
  await join.getByLabel('Dataset to join').selectOption({ label: CATALOGUE })
  // Both tables have an "item" column, so the key is suggested.
  await expect(join.getByLabel('Column in the main table')).toHaveValue('item')
  await expect(join.getByLabel('Matching column in the joined dataset')).toHaveValue('item')

  await builder.getByRole('button', { name: 'Preview the merge' }).click()
  await expect(builder.getByText('8 rows in, 8 rows out, 2 columns added.')).toBeVisible()
  await expect(builder.getByText(`${CATALOGUE}: 6 of 8 rows matched (75%).`)).toBeVisible()
  await expect(builder.getByText('No match for: K4')).toBeVisible()
  await expect(builder.getByRole('region', { name: 'First rows of the merged table' })).toContainText('Tools')
  await builder.getByLabel('Break totals down by').selectOption('family')
  await expect(builder.getByText('Changed since the preview.', { exact: false })).toBeVisible()
  await expectNoViolations(page, 'join preview')
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0)

  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({ timeout: 40_000 })
  await expect(page.getByText(`${ORDERS} + ${CATALOGUE}`).first()).toBeVisible()
  const disclosure = page.locator('.run-timeline__disclosure')
  if ((await disclosure.getAttribute('open')) === null) await disclosure.locator(':scope > summary').click()
  await expect(page.locator('.runtasks').getByText('Data Merge Agent', { exact: false })).toBeVisible()
  await expect(page.locator('.runtask--succeeded')).toHaveCount(22)

  // The merged table downloads as CSV, joined columns included (ADR 0031).
  const saving = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download cleaned data (CSV)' }).click()
  const download = await saving
  expect(download.suggestedFilename()).toMatch(/-cleaned\.csv$/)
  const text = await (await download.createReadStream()).toArray()
  const csv = Buffer.concat(text).toString('utf-8')
  expect(csv.replace(/^\ufeff/, '').split('\r\n')[0]).toBe('month,item,channel,amount,family,unit_cost')
  expect(csv).toContain('2025-02,K4,Store,60,,')
})

test('a lookup whose key repeats is refused with the reason', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  const orders = await startFromOrders(page)
  await openTab(page, /^Runs/)
  await page.getByRole('button', { name: 'Stored dataset' }).click()
  await page.getByLabel('Choose a stored dataset').selectOption(orders)
  const builder = page.getByRole('group', { name: 'Join other datasets (optional)' })
  await builder.getByRole('button', { name: 'Join a dataset' }).click()
  await builder.getByLabel('Dataset to join').selectOption({ label: DUPLICATED })
  await builder.getByRole('button', { name: 'Preview the merge' }).click()
  const alert = builder.getByRole('alert')
  await expect(alert).toContainText('The datasets cannot be merged')
  await expect(alert).toContainText('“K1” (2 times)')
  await expectNoViolations(page, 'join refusal')
})

test('the join builder in Arabic', async ({ page }) => {
  await skipOnboarding(page)
  await page.addInitScript(() => localStorage.setItem('aos-locale', 'ar'))
  await page.goto('/')
  const orders = await startFromOrders(page)
  await openArabicTab(page, /^التحليلات/)
  await page.getByRole('button', { name: 'مجموعة بيانات مخزنة' }).click()
  await page.locator('#run-stored').selectOption(orders)
  const builder = page.getByRole('group', { name: 'دمج مجموعات بيانات أخرى (اختياري)' })
  await builder.getByRole('button', { name: 'دمج مجموعة بيانات' }).click()
  await builder.getByLabel('البيانات المراد دمجها').selectOption({ label: CATALOGUE })
  await builder.getByRole('button', { name: 'معاينة الدمج' }).click()
  await expect(builder.getByText(/تطابق 6 من أصل 8 صفاً/)).toBeVisible()
  await expectNoViolations(page, 'Arabic join preview')
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0)
})
