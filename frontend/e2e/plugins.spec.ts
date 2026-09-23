import { expect, test } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

// A custom stage registered by the operator (examples/stages/
// target_attainment.py, behind the "with-target" profile in the e2e
// config) runs inside the same pipeline: it appears in the stage list,
// gets its own report tab, and its claim goes through the validator into
// the comprehensive report the approval gate binds to.
test('a registered custom stage runs under the same gate, chosen by profile', async ({
  page,
}) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Runs/)

  // The picker exists because profiles are configured; the default adds nothing.
  const picker = page.getByLabel('Pipeline profile')
  await expect(picker).toBeVisible()
  await expect(page.getByText('This one adds none.')).toBeVisible()
  await picker.selectOption('with-target')
  await expect(page.getByText('This one adds: Target Attainment Agent.')).toBeVisible()

  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })

  // In the pipeline list, after the sensitivity stage and before the auditors.
  const titles = await page.locator('.runtask .controlrow__label').allTextContents()
  const custom = titles.findIndex((t) => t.startsWith('Target Attainment Agent'))
  const sensitivity = titles.findIndex((t) => t.startsWith('Sensitivity Agent'))
  const provenance = titles.findIndex((t) => t.startsWith('Provenance Agent'))
  expect(custom).toBeGreaterThan(sensitivity)
  expect(custom).toBeLessThan(provenance)

  // Its own tab, named by its title, answering its own question.
  await page.getByRole('tab', { name: /Target Attainment Agent/ }).click()
  await expect(page.getByRole('tabpanel')).toContainText('Did we hit the target?')
  await expect(page.getByRole('tabpanel')).toContainText('of the target')

  // And the comprehensive report — the thing that gets approved — carries it.
  const full = page.locator('pre.runreport--full')
  await expect(full).toContainText('## Custom stages')
  await expect(full).toContainText('Target Attainment Agent')
  await expect(full).toContainText('target_attainment.c_attainment')
})
