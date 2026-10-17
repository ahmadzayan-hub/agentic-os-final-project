import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from '../features/chat/Composer'

describe('Composer', () => {
  it('retains a failed draft and restores it after remount', async () => {
    const user = userEvent.setup()
    const first = render(<Composer draftKey="failure-test" onSend={async () => false} busy={false} />)
    await user.type(screen.getByLabelText('Message'), 'Recover my question{Enter}')
    expect(screen.getByLabelText('Message')).toHaveValue('Recover my question')
    first.unmount()
    render(<Composer draftKey="failure-test" onSend={vi.fn()} busy={false} />)
    expect(screen.getByLabelText('Message')).toHaveValue('Recover my question')
  })
  it('sends trimmed text on Enter and clears the input', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={onSend} busy={false} />)

    const input = screen.getByLabelText('Message')
    await user.type(input, '  /help  {Enter}')

    expect(onSend).toHaveBeenCalledExactlyOnceWith('/help')
    expect(input).toHaveValue('')
  })

  it('adds a newline instead of sending on Shift+Enter', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={onSend} busy={false} />)

    const input = screen.getByLabelText('Message')
    await user.type(input, 'line one{Shift>}{Enter}{/Shift}line two')

    expect(onSend).not.toHaveBeenCalled()
    expect(input).toHaveValue('line one\nline two')
  })

  it('does not send empty or whitespace-only messages', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={onSend} busy={false} />)

    await user.type(screen.getByLabelText('Message'), '   {Enter}')

    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('blocks duplicate submission while a request is in flight', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={onSend} busy={true} />)

    const input = screen.getByLabelText('Message')
    await user.type(input, 'hello{Enter}')

    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled()
  })

  it('disables the input entirely when the session has ended', () => {
    render(<Composer onSend={vi.fn()} busy={false} disabled />)
    expect(screen.getByLabelText('Message')).toBeDisabled()
    expect(screen.getByPlaceholderText('This session has ended')).toBeInTheDocument()
  })
})

