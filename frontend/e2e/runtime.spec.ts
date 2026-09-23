import { expect, test } from '@playwright/test'
import { lastAgentBubble, sendMessage, skipOnboarding } from './helpers'

// An agent runtime (ADR 0021) gets the sentences the rules cannot place.
// What it called is in the bubble verbatim, its closing line after, and
// the label says who drove the tools and how many calls it took. An
// exact sentence still never reaches it.
test('a sentence the rules cannot place goes to the agent runtime, and its calls are shown', async ({
  page,
}) => {
  await skipOnboarding(page)
  await page.goto('/')

  await sendMessage(page, 'Please sort out the three things we discussed')
  await expect(lastAgentBubble(page)).toContainText('Here is what I can do')
  await expect(lastAgentBubble(page)).toContainText('Over to you.')
  await expect(page.getByText('run by Scripted · 1 tool call')).toBeVisible()

  await sendMessage(page, 'Remember that the Q4 review is on Monday')
  await expect(lastAgentBubble(page)).toHaveText('Information saved.')
  await expect(page.getByText(/run by Scripted/)).toHaveCount(1)

  // A sentence the runtime declines is answered the ordinary way.
  await sendMessage(page, 'Ping')
  await expect(lastAgentBubble(page)).toContainText('not sure what')
  await expect(page.getByText(/run by Scripted/)).toHaveCount(1)
})
