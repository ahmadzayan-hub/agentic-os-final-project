import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageBubble } from '../features/chat/MessageBubble'
import { cardType } from '../features/chat/ResultCard'
import type { TranscriptEntry } from '../shared/types'

const entry: TranscriptEntry = { id: 1, role: 'agent', text: '<img src=x onerror=alert(1)>', time: '2026-10-16T10:00:00Z', action: 'unknown-card' }
describe('typed assistant results', () => {
  it('falls back to ordinary text for an unknown action', () => {
    expect(cardType(entry)).toBeNull()
    const { container } = render(<MessageBubble entry={entry} agentName="Test Agent" />)
    expect(screen.getByText(entry.text)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('.result-card')).toBeNull()
  })
  it('only creates a run card for a known action and a returned identifier', () => {
    expect(cardType({ ...entry, action: 'start_run' })).toBeNull()
    expect(cardType({ ...entry, action: 'start_run', result: { run_id: 'run-test' } })).toBe('run')
    expect(cardType({ ...entry, action: 'explain_report', result: { run_id: 'run-test' } })).toBe('run')
    expect(cardType({ ...entry, action: 'runtime', result: { run_id: 'run-test' } })).toBe('run')
    expect(cardType({ ...entry, role: 'user', action: 'start_run', result: { run_id: 'run-test' } })).toBeNull()
  })
})
