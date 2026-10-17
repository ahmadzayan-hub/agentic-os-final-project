import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import { skipOnboarding } from './helpers'

// Model cards (ADR 0033). The e2e config registers the four modelling
// stages behind the "models" profile. On the bundled sample (72 records,
// 12 months) the regression, classification and clustering stages each
// report a card with the verdict first; the seasonal forecast has too
// little history, says so as a limitation and shows no card.

test.use({ contextOptions: { reducedMotion: 'reduce' } })

async function modelledRun(request: APIRequestContext, goal: string, language = 'en') {
  let run = await (await request.post('/api/runs', { data: { goal, profile: 'models', language } })).json()
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

async function openRun(page: Page, runId: string) {
  await page.goto(`/#/runs/${runId}`)
  await page.locator('.viewload').waitFor({ state: 'detached' })
}

test('each model card says whether the model beats its baseline', async ({ page }) => {
  await skipOnboarding(page)
  const runId = await modelledRun(page.request, 'Model the sample')
  await openRun(page, runId)

  const cards = page.getByRole('region', { name: 'Models, each against a plain guess' })
  await expect(cards.locator('article')).toHaveCount(3)
  const regression = cards.locator('article', { hasText: 'Regression Model Agent' })
  await expect(regression).toContainText('Beats its baseline by 90%')
  await expect(regression).toContainText('Average error on held-out data')
  await expect(regression).toContainText('the training average')
  await expect(regression).toContainText('Tested on the latest periods, from 2025-10')
  await expect(cards.locator('article', { hasText: 'Classification Model Agent' })).toContainText(
    'always the most common class',
  )
  const clustering = cards.locator('article', { hasText: 'Clustering Model Agent' })
  await expect(clustering).toContainText(/groups found, explaining 92% of the spread/)
  await expect(clustering).toContainText('Records used: 72')
  await expect(cards).not.toContainText('Seasonal Forecast Agent')

  await expectNoViolations(page, 'model cards')
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  ).toBeLessThanOrEqual(0)
})

test('model cards in Arabic', async ({ page }) => {
  await skipOnboarding(page)
  await page.addInitScript(() => localStorage.setItem('aos-locale', 'ar'))
  const runId = await modelledRun(page.request, 'نماذج بالعربية', 'ar')
  await openRun(page, runId)

  const cards = page.getByRole('region', { name: 'النماذج، كلٌّ مقابل تخمين بسيط' })
  await expect(cards.locator('article')).toHaveCount(3)
  await expect(cards).toContainText('وكيل نموذج التنبؤ بالمقياس')
  await expect(cards).toContainText('يتفوّق على خط الأساس بنسبة')
  await expect(cards).toContainText('متوسط بيانات التعلّم')
  await expectNoViolations(page, 'Arabic model cards')
})
