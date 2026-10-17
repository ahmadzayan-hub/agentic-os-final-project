import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { openTab, skipOnboarding } from './helpers'

// The dataset API through the browser (ADR 0024): a file of each format
// added in the Datasets view and read by the server, the same data never
// stored twice, and a workbook analysed from the Runs view.
//
// Datasets are content-addressed per owner and this database is shared
// by every spec and both viewports, so a file may already be stored when
// a test uploads it. Each table here is used by this spec alone, and the
// assertions accept "added" and "already stored" alike where it matters.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

const WORKBOOK = fileURLToPath(new URL('./fixtures/regional-sales.xlsx', import.meta.url))

async function expectNoViolations(page: Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  expect(
    results.violations,
    `${context}: ${results.violations.map((v) => `${v.id} (${v.nodes.length})`).join(', ')}`,
  ).toEqual([])
}

/** Add a file the way a person does: the button, then the file picker. */
async function addDataset(page: Page, files: Parameters<import('@playwright/test').FileChooser['setFiles']>[0]) {
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Add a dataset' }).first().click()
  await (await chooser).setFiles(files)
}

test('a CSV, a workbook and a JSON file are each read and listed with what they are', async ({
  page,
}) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Datasets/)

  // Semicolons, as Excel saves CSV in many locales.
  await addDataset(page, {
    name: 'cost-centres.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('centre;month;cost\nOps;2025-01;410\nOps;2025-02;395\nIT;2025-01;220\n'),
  })
  const status = page.getByRole('status').filter({ hasText: 'cost-centres.csv' })
  await expect(status).toContainText(/Added cost-centres.csv: 3 data rows\.|holds the same data/)

  await addDataset(page, WORKBOOK)
  await expect(page.getByRole('status').filter({ hasText: 'regional-sales.xlsx' })).toBeVisible()

  await addDataset(page, {
    name: 'targets.json',
    mimeType: 'application/json',
    buffer: Buffer.from(
      JSON.stringify({ data: [{ team: 'A', target: { q1: 150 } }, { team: 'B', target: { q1: 90 } }] }),
    ),
  })
  await expect(page.getByRole('status').filter({ hasText: 'targets.json' })).toBeVisible()

  const row = (name: string) => page.locator('.dataset').filter({ hasText: name })
  await expect(row('cost-centres.csv')).toContainText('CSV · 3 data rows')
  await expect(row('regional-sales.xlsx')).toContainText('Excel · 4 data rows')
  await expect(row('targets.json')).toContainText('JSON · 2 data rows')
  await expectNoViolations(page, 'datasets view after uploads')

  // The same bytes again: the server says so, and nothing new is stored.
  await addDataset(page, {
    name: 'cost-centres-copy.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('centre,month,cost\nOps,2025-01,410\nOps,2025-02,395\nIT,2025-01,220\n'),
  })
  // Scoped to the page: the header's connection badge is a status too.
  await expect(
    page.getByRole('region', { name: 'Datasets' }).getByRole('status').filter({ hasText: 'cost-centres' }),
  ).toContainText('cost-centres.csv holds the same data as a dataset already stored')
  await expect(row('cost-centres-copy.csv')).toHaveCount(0)
  // A refresh after an upload keeps the list on screen.
  await expect(page.getByRole('status', { name: 'Loading your datasets' })).toHaveCount(0)
})

test('a file the server cannot read is explained, not stored', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Datasets/)
  await addDataset(page, {
    name: 'legacy.xls',
    mimeType: 'application/vnd.ms-excel',
    buffer: Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, 0, 0, 0, 0]),
  })
  await expect(page.getByRole('alert')).toContainText('Save it as .xlsx or CSV')
  await expect(page.locator('.dataset').filter({ hasText: 'legacy.xls' })).toHaveCount(0)
})

test('a workbook uploaded in the Runs view is analysed by reference', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Runs/)
  await page.getByRole('button', { name: 'Upload a file or paste CSV', exact: true }).click()
  await page.getByLabel('Choose a file').setInputFiles(WORKBOOK)
  await expect(page.getByRole('status').filter({ hasText: 'regional-sales.xlsx' })).toContainText(
    '4 data rows · Excel',
  )
  // The workbook has two sheets; the server says which one it read.
  await expect(page.getByText('Read the sheet “Sales”, the first of 2.')).toBeVisible()
  await expect(page.getByLabel('Goal')).toHaveValue(
    'Analyse regional-sales.xlsx and produce a business report',
  )

  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })
  // Figures come from the workbook: four rows of revenue, 4,430 in all.
  await expect(page.locator('.runreport--full')).toContainText('regional-sales.xlsx')
  await expect(page.locator('.runreport--full')).toContainText('4430')
})
