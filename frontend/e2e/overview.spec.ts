import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

// The Overview and Datasets views (ADR 0023, phase 1): what the
// workspace found, what waits for approval, and a stored dataset
// analysed again without being uploaded twice.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

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
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
}

/** Run the sample analysis up to the approval gate, so the Overview has
 *  findings and a run waiting, and the Datasets view a stored dataset. */
async function runSampleToApproval(page: Page) {
  await openTab(page, /^Runs/)
  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })
}

test('the overview shows the figures, the latest findings and what waits for approval', async ({
  page,
}) => {
  await skipOnboarding(page)
  await page.goto('/')
  await runSampleToApproval(page)

  await openTab(page, /^Overview/)
  await expect(page.getByRole('heading', { name: 'Overview', level: 2 })).toBeVisible()
  await expect(page.locator('.kpi')).toHaveCount(4)
  // A run is at the gate, so the one amber tile is lit.
  await expect(page.locator('.kpi--attention')).toContainText('Waiting for approval')
  await expect(page.locator('.finding').first()).toBeVisible()
  await expect(page.locator('.finding__type').first()).toHaveText('Descriptive')
  await expectNoViolations(page, 'overview')

  // Review opens the waiting run on its approval card.
  await page.getByRole('button', { name: /Review$/ }).first().click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible()
  await expect(page.getByText('state: awaiting approval')).toBeVisible()
})

test('a stored dataset is analysed again by reference', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await runSampleToApproval(page)

  await openTab(page, /^Datasets/)
  await expect(page.getByRole('heading', { name: 'Datasets', level: 2 })).toBeVisible()
  // Content-addressed: however many runs used the sample, it is stored once.
  await expect(page.locator('.dataset__name').filter({ hasText: 'sample sales dataset' })).toHaveCount(1)
  await expectNoViolations(page, 'datasets')

  await page.getByRole('button', { name: 'Analyse sample sales dataset' }).click()
  await expect(page.getByRole('button', { name: 'Stored dataset', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const picker = page.getByLabel('Choose a stored dataset')
  await expect(picker.locator('option:checked')).toContainText('sample sales dataset · 72 data rows')
  await expect(page.getByText('nothing is uploaded again')).toBeVisible()
  await expect(page.getByLabel('Goal')).toHaveValue('Analyse sample sales dataset and produce a business report')
  // The upload fields are not offered for a dataset that is already stored.
  await expect(page.getByLabel('Choose a file')).toHaveCount(0)
  await expectNoViolations(page, 'runs form with a stored dataset')

  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.locator('.cockpit__header .panel__desc')).toContainText('sample sales dataset')
  // Stop it here: what matters is which dataset it started from.
  await page.getByRole('button', { name: 'Pause' }).click()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByText('state: cancelled')).toBeVisible()

  // Going back to the sample puts its goal back; the upload fields are
  // one choice away.
  await openTab(page, /^Datasets/)
  await page.getByRole('button', { name: 'Analyse sample sales dataset' }).click()
  await page.getByRole('button', { name: 'Sample sales data', exact: true }).click()
  await expect(page.getByLabel('Goal')).toHaveValue(/^Analyze the sample sales dataset/)
  await page.getByRole('button', { name: 'Upload a file or paste CSV', exact: true }).click()
  await expect(page.getByLabel('Choose a file')).toBeVisible()
})

test('the phone bar holds five places and More opens the rest', async ({ page }) => {
  test.skip(test.info().project.name !== 'mobile', 'the bottom bar exists on phones only')
  await skipOnboarding(page)
  await page.goto('/')

  const bar = page.getByRole('navigation', { name: 'Primary' })
  await expect(bar.getByRole('button')).toHaveCount(5)
  await bar.getByRole('button', { name: 'Overview' }).click()
  await expect(bar.getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')

  const more = bar.getByRole('button', { name: 'More' })
  await more.click()
  const drawer = page.getByRole('dialog', { name: 'Navigation' })
  await expect(drawer).toBeVisible()
  await drawer.getByRole('button', { name: /^Memory/ }).click()
  await expect(drawer).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Saved memory', level: 2 })).toBeVisible()
  // Focus returns to the control that opened the drawer.
  await expect(more).toBeFocused()
})

test('the new views do not scroll sideways at 320 px, in either language', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'viewport-resize test runs once')
  await page.addInitScript(() => localStorage.setItem('aos-onboarded', '1'))
  await page.goto('/')
  await page.setViewportSize({ width: 320, height: 640 })

  for (const name of [/^Overview/, /^Datasets/, /^Runs/]) {
    await openTab(page, name)
    await expect(page.locator('main .panel__title:visible')).toBeVisible()
    await expect(page.locator('main .skeleton:visible')).toHaveCount(0)
    expect(await horizontalOverflow(page), `overflow on ${name}`).toBeLessThanOrEqual(0)
  }

  // Arabic labels are longer; the bar and the views must still fit.
  await page.getByRole('button', { name: 'Change language' }).click()
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
  for (const name of [/^نظرة عامة/, /^مجموعات البيانات/]) {
    const menu = page.getByRole('button', { name: 'فتح قائمة التنقل' })
    await menu.click()
    await page.getByRole('dialog').getByRole('button', { name }).click()
    await expect(page.locator('main .panel__title:visible')).toBeVisible()
    await expect(page.locator('main .skeleton:visible')).toHaveCount(0)
    expect(await horizontalOverflow(page), `overflow on ${name}`).toBeLessThanOrEqual(0)
    await expectNoViolations(page, `${name} in Arabic`)
  }
})

test.describe('a view that cannot load', () => {
  // The service worker would fetch the chunk itself, out of the page's
  // reach; with it blocked, the page asks the network as a reader with
  // nothing cached would.
  test.use({ serviceWorkers: 'block' })

  test('says so, and the next view still opens', async ({ page }) => {
    // Views load on demand (ADR 0028). Refusing one chunk stands in for a
    // reader who went offline before it was ever fetched.
    await skipOnboarding(page)
    await page.route(/\/assets\/OverviewView-[^/]+\.js$/, (route) => route.abort())
    await page.goto('/')

    await openTab(page, /^Overview/)
    await expect(page.getByRole('alert')).toContainText('This view could not be shown')
    await expect(page.getByRole('button', { name: 'Reload the page' })).toBeVisible()
    await expectNoViolations(page, 'a view that could not load')

    await openTab(page, /^Datasets/)
    await expect(page.getByRole('heading', { name: 'Datasets', level: 2 })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
})
