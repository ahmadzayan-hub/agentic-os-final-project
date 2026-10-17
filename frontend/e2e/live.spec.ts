import AxeBuilder from '@axe-core/playwright'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page, TestInfo } from '@playwright/test'
import { skipOnboarding } from './helpers'

// Live data (ADR 0034). The e2e server reads sources from a folder at the
// reserved https://fixtures.invalid/ host, so these tests write the
// "remote" file themselves: a live source is added and refreshed from the
// Datasets view; a dashboard over one snapshot offers the next; and the
// connection badge says when it is reconnecting or offline.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

const SOURCES = fileURLToPath(new URL('./.tmp/sources/', import.meta.url))

function writeSource(name: string, months: number) {
  const lines = ['month,region,revenue']
  for (let i = 0; i < months; i += 1) {
    const month = `${2025 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`
    lines.push(`${month},North,${100 + 7 * i}`, `${month},South,${80 + 3 * i}`)
  }
  writeFileSync(`${SOURCES}${name}`, `${lines.join('\n')}\n`)
}

function sourceName(info: TestInfo, tag: string) {
  return `${tag}-${info.project.name}.csv`
}

async function finish(request: APIRequestContext, runId: string) {
  let run = await (await request.get(`/api/runs/${runId}`)).json()
  for (let step = 0; step < 80 && ['queued', 'running'].includes(run.state); step += 1) {
    run = await (await request.post(`/api/runs/${runId}/advance`)).json()
  }
  expect(run.state).toBe('awaiting_approval')
}

async function removeConnectors(request: APIRequestContext, name: string) {
  const { connectors } = await (await request.get('/api/connectors')).json()
  for (const item of connectors.filter((entry: { name: string }) => entry.name === name)) {
    await request.delete(`/api/connectors/${item.id}`)
  }
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

test('a live source is added, refreshed and opened from the Datasets view', async ({ page }, info) => {
  const file = sourceName(info, 'sales')
  const name = `Sales ${info.project.name}`
  writeSource(file, 12)
  await removeConnectors(page.request, name)
  await skipOnboarding(page)
  await page.goto('/#/datasets')
  await page.locator('.viewload').waitFor({ state: 'detached' })

  const panel = page.getByRole('region', { name: 'Live sources' })
  await expect(panel.locator('.live-badge')).toHaveText('Live')
  await panel.getByText('Add a live source').click()
  await panel.getByLabel('Name').fill(name)
  await panel.getByLabel('Address (https)').fill(`https://fixtures.invalid/${file}`)
  await panel.getByRole('button', { name: 'Add source' }).click()

  const row = panel.locator('.live-source', { hasText: name })
  await expect(row).toContainText('Not refreshed yet.')
  await row.getByRole('button', { name: `Refresh ${name} now` }).click()
  await expect(row).toContainText('New data at', { timeout: 15_000 })
  await expect(row.getByRole('link', { name: 'Open analysis' })).toBeVisible()
  await expectNoViolations(page, 'live sources')
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  ).toBeLessThanOrEqual(0)

  await row.getByRole('button', { name: `Refresh ${name} now` }).click()
  await expect(row).toContainText('No change at', { timeout: 15_000 })
  await removeConnectors(page.request, name)
})

test('a dashboard over one snapshot offers the next one', async ({ page }, info) => {
  const file = sourceName(info, 'follow')
  const name = `Follow ${info.project.name}`
  writeSource(file, 12)
  await removeConnectors(page.request, name)
  const connector = await (
    await page.request.post('/api/connectors', {
      data: { name, url: `https://fixtures.invalid/${file}`, goal: 'Revenue by region' },
    })
  ).json()
  const first = await (await page.request.post(`/api/connectors/${connector.id}/refresh`)).json()
  expect(first.status).toBe('updated')
  await finish(page.request, first.run)

  await skipOnboarding(page)
  await page.goto(`/#/dashboard/${first.run}`)
  await page.locator('.viewload').waitFor({ state: 'detached' })
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 24 of 24 records.')
  await expect(page.locator('.live-badge')).toHaveText('Live')

  writeSource(file, 13)
  const second = await (await page.request.post(`/api/connectors/${connector.id}/refresh`)).json()
  expect(second.status).toBe('updated')
  await finish(page.request, second.run)

  await expect(page.getByText('A newer snapshot of this source has been analysed.')).toBeVisible({
    timeout: 15_000,
  })
  await expectNoViolations(page, 'newer snapshot notice')
  await page.getByRole('button', { name: 'Open the newer analysis' }).click()
  await expect(page).toHaveURL(new RegExp(`#/dashboard/${second.run}`))
  await expect(page.locator('.dash-coverage')).toHaveText('Showing 26 of 26 records.')
  await removeConnectors(page.request, name)
})

test('the badge says when it is reconnecting or offline, in Arabic', async ({ page, context }) => {
  await skipOnboarding(page)
  await page.addInitScript(() => localStorage.setItem('aos-locale', 'ar'))
  await page.route('**/api/events*', (route) => route.fulfill({ status: 503, body: '' }))
  await page.goto('/#/datasets')
  await page.locator('.viewload').waitFor({ state: 'detached' })
  const badge = page.getByRole('region', { name: 'المصادر الحية' }).locator('.live-badge')
  await expect(badge).toHaveText('جارٍ إعادة الاتصال…')

  await page.unroute('**/api/events*')
  await expect(badge).toHaveText('مباشر', { timeout: 15_000 })
  await expectNoViolations(page, 'Arabic live sources')

  await context.setOffline(true)
  await expect(badge).toContainText('غير متصل')
  await expect(badge).toContainText('آخر تحديث')
  await context.setOffline(false)
  await expect(badge).toHaveText('مباشر', { timeout: 15_000 })
})
