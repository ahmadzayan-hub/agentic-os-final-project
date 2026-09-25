import { expect, test } from '@playwright/test'
import { clickQuickAction, composerInput, lastAgentBubble, openTab, sendMessage, skipOnboarding } from './helpers'

test.describe('main user journey', () => {
  const consoleErrors: string[] = []

  test.beforeEach(async ({ page }) => {
    consoleErrors.length = 0
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => consoleErrors.push(String(error)))
    await skipOnboarding(page)
  })

  test('conversation, memory, preferences, history, and session lifecycle', async ({ page }) => {
    // 1. Start the application and open a session.
    await page.goto('/')
    await expect(page.getByRole('status').filter({ hasText: 'Ready' })).toBeVisible()
    await expect(page.getByText('Welcome to Agentic OS (version 1.0.0)')).toBeVisible()

    // 2. Send a message.
    await sendMessage(page, 'Hello there')
    await expect(page.locator('.msg--user .msg__bubble').last()).toHaveText('Hello there')
    await expect(lastAgentBubble(page)).toContainText('Happy to help')

    // 3. Save a memory with a slash command.
    await sendMessage(page, '/remember My preferred language is English')
    await expect(lastAgentBubble(page)).toHaveText('Information saved.')

    // 4. Manage memory in the Memory panel: add, edit, export, delete.
    await openTab(page, /^Memory/)
    await expect(page.getByText('My preferred language is English')).toBeVisible()

    await page.getByLabel('Information to remember').fill('Coffee at 8am')
    await page.getByLabel('Category', { exact: true }).selectOption('work')
    await page.getByRole('button', { name: 'Add memory' }).click()
    await expect(page.getByText('Coffee at 8am')).toBeVisible()
    await expect(page.locator('.memory__item')).toHaveCount(2)

    // Category filters narrow the list; All restores it.
    await page.getByRole('button', { name: 'Work', exact: true }).click()
    await expect(page.locator('.memory__item')).toHaveCount(1)
    await expect(page.getByText('Coffee at 8am')).toBeVisible()
    await page.getByRole('button', { name: 'All', exact: true }).click()
    await expect(page.locator('.memory__item')).toHaveCount(2)

    await page.getByRole('button', { name: 'Edit memory_2' }).click()
    await page.getByLabel('Edit memory_2').fill('Coffee at 7am sharp')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Coffee at 7am sharp')).toBeVisible()

    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: /Export my data/ }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('agentic-os-export.json')

    // Individual deletion is destructive and must be confirmed.
    await page.getByRole('button', { name: /Forget memory_2/ }).click()
    const confirmForget = page.getByRole('dialog', { name: 'Forget memory_2?' })
    await expect(confirmForget).toBeVisible()
    await confirmForget.getByRole('button', { name: 'Forget it' }).click()
    await expect(page.locator('.memory__item')).toHaveCount(1)

    // 5. Change preferences and see them applied to replies.
    await openTab(page, /^Preferences/)
    await page.getByRole('button', { name: 'Concise' }).click()
    await expect(page.getByText('Preference updated: tone = concise.')).toBeVisible()

    await page.getByLabel('Your name').fill('Ahmad')
    await page.getByRole('button', { name: 'Save', exact: true }).first().click()
    await expect(page.getByText('Preference updated: user_name = Ahmad.')).toBeVisible()

    await openTab(page, /^Workspace/)
    // A sentence the assistant cannot act on gets an honest, tone-shaped
    // answer that says what can be asked — concise here.
    await sendMessage(page, 'Ping')
    await expect(lastAgentBubble(page)).toContainText('Not sure what to do with “Ping”')

    // 6. View history.
    await sendMessage(page, '/history')
    await expect(lastAgentBubble(page)).toContainText('Hello there')
    await expect(lastAgentBubble(page)).toContainText('Ping')

    // 7. Clear history with confirmation (from Memory > Data controls).
    await openTab(page, /^Memory/)
    await page.getByRole('button', { name: /Clear conversation history/ }).click()
    const confirmClear = page.getByRole('dialog', { name: 'Clear conversation history?' })
    await expect(confirmClear).toBeVisible()
    await confirmClear.getByRole('button', { name: 'Clear history' }).click()
    await expect(confirmClear).toBeHidden()

    await openTab(page, /^Workspace/)
    await sendMessage(page, '/history')
    await expect(lastAgentBubble(page)).toHaveText('No conversation history is available.')

    // 8. Delete all memory with confirmation (also resets shared e2e state).
    await openTab(page, /^Memory/)
    await page.getByRole('button', { name: /Delete all memory/ }).click()
    const confirmMemory = page.getByRole('dialog', { name: 'Delete all memory?' })
    await confirmMemory.getByRole('button', { name: 'Delete all memory' }).click()
    await expect(page.getByText('Nothing saved yet.', { exact: false })).toBeVisible()

    // 9. End the session gracefully, then start a new one.
    await clickQuickAction(page, /^End session/)
    const confirmEnd = page.getByRole('dialog', { name: 'End this session?' })
    await confirmEnd.getByRole('button', { name: 'End session' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Session ended' })).toBeVisible()

    await openTab(page, /^Workspace/)
    await expect(page.getByText('This session has ended.', { exact: false }).first()).toBeVisible()
    await expect(composerInput(page)).toBeDisabled()

    await clickQuickAction(page, /^New session/)
    await expect(composerInput(page)).toBeEnabled()
    await expect(page.getByText('Welcome to Agentic OS (version 1.0.0)')).toBeVisible()

    // 10. The whole journey must produce no browser console errors.
    expect(consoleErrors).toEqual([])
  })

  test('command palette inserts commands and unknown commands fail gracefully', async ({ page }) => {
    await page.goto('/')
    await expect(composerInput(page)).toBeVisible()

    await page.keyboard.press('ControlOrMeta+k')
    const palette = page.getByRole('dialog', { name: 'Command palette' })
    await expect(palette).toBeVisible()
    await page.keyboard.type('help')
    await page.keyboard.press('Enter')
    await expect(palette).toBeHidden()

    const input = composerInput(page)
    await expect(input).toHaveValue('/help')
    await input.press('Enter')
    await expect(lastAgentBubble(page)).toContainText('Available commands:')

    await sendMessage(page, '/teleport')
    await expect(lastAgentBubble(page)).toContainText('Unknown command: /teleport')
    expect(consoleErrors).toEqual([])
  })

  test('layout has no horizontal overflow', async ({ page }) => {
    await page.goto('/')
    await expect(composerInput(page)).toBeVisible()
    await sendMessage(page, 'A fairly long message that should wrap correctly on small screens without causing any horizontal scrolling anywhere in the layout.')
    await expect(lastAgentBubble(page)).toBeVisible()

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
