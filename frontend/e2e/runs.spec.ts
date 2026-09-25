import { expect, test } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

test('analytics run: goal to approved, published, evidence-backed report', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Runs/)

  await expect(page.getByLabel('Goal')).toHaveValue(/sample sales dataset/)
  await page.getByRole('button', { name: 'Start run' }).click()

  // The pipeline advances stage by stage until the approval gate.
  const approval = page.getByRole('region', { name: 'Approval required' })
  await expect(approval).toBeVisible({ timeout: 40_000 })
  await expect(approval).toContainText('high')
  await expect(page.getByText('state: awaiting approval')).toBeVisible()

  // Every specialist succeeded and the evidence is visible. Twenty-one
  // stages; the twenty-second task is the publish gate, still waiting.
  await expect(page.locator('.runtask--succeeded')).toHaveCount(21)
  await expect(
    page.locator('.runtasks').getByText('All validation checks passed', { exact: false }),
  ).toBeVisible()
  await expect(page.locator('.runchart__svg')).toHaveCount(4)
  await expect(page.locator('.runreport--full')).toContainText('Every claim in this report')
  await expect(page.locator('.runreport--full')).toContainText('verified')

  // Approve: the report is published to the Obsidian-compatible vault.
  await approval.getByRole('button', { name: 'Approve and publish' }).click()
  await expect(page.getByText('published to the vault', { exact: false })).toBeVisible()
  await expect(page.getByText('state: completed')).toBeVisible()
})

test('an analytics run can be paused and then cancelled', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Runs/)
  await page.getByRole('button', { name: 'Start run' }).click()

  // Pause first so the pipeline stops advancing; cancelling is then a
  // deterministic decision rather than a race against the next stage.
  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()

  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByText('state: cancelled')).toBeVisible()
  // A cancelled run is terminal: no further stages may run.
  await expect(page.getByRole('button', { name: 'Resume' })).toHaveCount(0)
})

test('a CSV file can be uploaded and is analyzed', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Runs/)

  await page.getByRole('button', { name: 'Upload or paste CSV' }).click()
  await page.getByLabel('Choose a CSV file').setInputFiles({
    name: 'quarterly-sales.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('team,quarter,sales\nA,Q1,120\nA,Q2,180\nB,Q1,60\nB,Q2,40\n'),
  })
  // The file is read in the browser and its shape confirmed before sending.
  await expect(page.getByText('quarterly-sales.csv · 4 data rows')).toBeVisible()

  await page.getByLabel('Goal').fill('Analyze the uploaded quarterly sales')
  await page.getByRole('button', { name: 'Start run' }).click()

  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })
  // Figures come from the uploaded file, not the bundled sample.
  await expect(page.locator('.runreport--full')).toContainText('total_sales | 400.0')
  await expect(page.locator('.runreport--full')).toContainText('quarterly-sales.csv')
})
