import { expect, test } from '@playwright/test'
import { openTab, skipOnboarding } from './helpers'

test('the report tabs follow the keyboard tabs pattern', async ({ page }) => {
  await skipOnboarding(page)
  await page.goto('/')
  await openTab(page, /^Runs/)
  await page.getByRole('button', { name: 'Start run' }).click()
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })

  const tab = (name: RegExp) => page.getByRole('tab', { name })
  await tab(/descriptive/i).focus()
  await expect(tab(/descriptive/i)).toHaveAttribute('aria-selected', 'true')

  // Right moves to the next question in the ladder, and selection follows
  // focus so the panel below matches what is focused.
  await page.keyboard.press('ArrowRight')
  await expect(tab(/diagnostic/i)).toBeFocused()
  await expect(tab(/diagnostic/i)).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tabpanel')).toContainText('Why did it happen?')

  // The causal check sits right after the stage that finds associations.
  // The stage's role is "experiment"; the reader sees it as the causal
  // question, which is what the tab is named.
  await page.keyboard.press('ArrowRight')
  await expect(tab(/causal/i)).toBeFocused()
  await expect(page.getByRole('tabpanel')).toContainText('Can we claim a cause?')

  await page.keyboard.press('End')
  await expect(tab(/prescriptive/i)).toBeFocused()
  await expect(page.getByRole('tabpanel')).toContainText('What should I do?')

  // Wrapping keeps a keyboard user from getting stuck at either end.
  await page.keyboard.press('ArrowRight')
  await expect(tab(/descriptive/i)).toBeFocused()
  await page.keyboard.press('ArrowLeft')
  await expect(tab(/prescriptive/i)).toBeFocused()
  await page.keyboard.press('Home')
  await expect(tab(/descriptive/i)).toBeFocused()

  // Roving tabindex: the tablist is one stop, not five.
  await expect(page.getByRole('tab', { selected: false }).first()).toHaveAttribute(
    'tabindex',
    '-1',
  )
  await expect(tab(/descriptive/i)).toHaveAttribute('tabindex', '0')

  // One more Tab reaches the report text, which scrolls — a scrollable
  // region no keyboard can reach is a wall, and axe flags it as one.
  await page.keyboard.press('Tab')
  await expect(page.getByRole('region', { name: 'descriptive report text' })).toBeFocused()
})
