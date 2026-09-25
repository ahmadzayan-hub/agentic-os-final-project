import { expect, test } from '@playwright/test'
import { lastAgentBubble, openTab, sendMessage, skipOnboarding } from './helpers'

// The chat understands plain language and acts on it: a sentence saves a
// memory, starts an analysis, or explains the latest report — and a
// sentence that would delete something is confirmed first.
test('plain language in the chat saves, analyses, explains, and confirms before deleting', async ({
  page,
}) => {
  await skipOnboarding(page)
  await page.goto('/')

  await sendMessage(page, 'Remember that the Q4 review is on Monday')
  await expect(lastAgentBubble(page)).toHaveText('Information saved.')
  await sendMessage(page, 'What do you remember?')
  await expect(lastAgentBubble(page)).toContainText('the Q4 review is on Monday')

  // Starting a run from the chat opens it: the person sees the pipeline
  // rather than being told where to find it.
  await sendMessage(page, 'Analyse the sample sales data')
  await expect(page.getByRole('region', { name: 'Approval required' })).toBeVisible({
    timeout: 40_000,
  })

  await openTab(page, /^Workspace/)
  await expect(lastAgentBubble(page)).toContainText('Started analysis')
  await sendMessage(page, 'What should we do?')
  await expect(lastAgentBubble(page)).toContainText('What should I do?')
  await expect(lastAgentBubble(page)).toContainText('The full report')

  // Deletion is never a single sentence away.
  await sendMessage(page, 'Forget everything')
  await expect(lastAgentBubble(page)).toContainText('Reply “yes” to confirm')
  await sendMessage(page, 'no')
  await expect(lastAgentBubble(page)).toHaveText('Nothing was changed.')
  await openTab(page, /^Memory/)
  await expect(page.getByText('the Q4 review is on Monday')).toBeVisible()

  await openTab(page, /^Workspace/)
  await sendMessage(page, 'Forget everything')
  await sendMessage(page, 'yes')
  await expect(lastAgentBubble(page)).toHaveText('All saved information has been removed.')
})
