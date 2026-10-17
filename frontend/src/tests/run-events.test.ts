import { describe, expect, it } from 'vitest'
import { appendEvents, snapshotEvents } from '../features/runs/runEvents'
import { planRoles, roleBand } from '../features/runs/pipeline'
import { reportCalculations } from '../features/runs/evidence'
import { runFixture } from './run-fixture'

describe('observations of durable run snapshots', () => {
  it('does not invent stage-start events between observed snapshots', () => {
    const before = runFixture()
    const after = runFixture({ state: 'running', updated_at: '2026-10-16T10:01:00Z', tasks: [{ ...before.tasks[0], state: 'succeeded' }] })
    const events = snapshotEvents(before, after)
    expect(events.filter((event) => event.kind === 'stage.changed').map((event) => event.state)).toEqual(['succeeded'])
    expect(events.every((event) => event.time === after.updated_at)).toBe(true)
    expect(snapshotEvents(after, after)).toEqual([])
  })
  it.each(['failed', 'cancelled', 'partially_completed', 'completed'] as const)('records the observed %s outcome', (state) => {
    expect(snapshotEvents(runFixture(), runFixture({ state })).some((event) => event.kind === 'run.finished' && event.state === state)).toBe(true)
  })
  it('distinguishes durable pause and resume from a terminal state', () => {
    const paused = runFixture({ paused: true })
    expect(snapshotEvents(runFixture(), paused).map((event) => event.kind)).toEqual(['run.paused'])
    expect(snapshotEvents(paused, runFixture()).map((event) => event.kind)).toEqual(['run.resumed'])
  })
  it('records an approval interrupt without calling it publication', () => {
    const next = runFixture({ state: 'awaiting_approval', approvals: [{ id: 'approval-test', action: 'Publish', target: 'synthetic-vault', risk: 'high', impact: 'Test', reversibility: 'Test', state: 'pending', created_at: '2026-10-16T10:00:00Z', decided_at: null }] })
    const events = snapshotEvents(runFixture(), next)
    expect(events.some((event) => event.kind === 'approval.requested')).toBe(true)
    expect(events.some((event) => event.kind === 'artifact.published')).toBe(false)
  })
  it('only records publication from a returned publication path', () => {
    const before = runFixture({ report: { id: 'report-test', name: 'Test report', version: 1, content: '', published_path: null } })
    const after = runFixture({ report: { ...before.report!, published_path: 'Reports/test.md' } })
    expect(snapshotEvents(before, after).filter((event) => event.kind === 'artifact.published')).toHaveLength(1)
  })
  it('deduplicates repeated observations and bounds the timeline', () => {
    const event = snapshotEvents(null, runFixture())[0]
    expect(appendEvents([], [event, event])).toHaveLength(1)
    expect(appendEvents([], Array.from({ length: 130 }, (_, i) => ({ ...event, id: String(i) })))).toHaveLength(120)
  })
})

describe('profile plan and evidence boundary', () => {
  it('places a custom stage after its declared predecessor', () => {
    const pipelines = { stages: [{ role: 'target', title: 'Target', after: 'prescriptive', question: null, can_fail_run: false }], profiles: { target: ['target'] }, default: [], problems: [] }
    const roles = planRoles(pipelines, 'target')
    expect(roles[roles.indexOf('prescriptive') + 1]).toBe('target')
    expect(roleBand('target', pipelines)).toBe('analytics')
    expect(roles.at(-1)).toBe('publish')
    expect(planRoles(pipelines, '')).not.toContain('target')
  })
  it('merges joined datasets right after cleaning, and only when there are joins (ADR 0030)', () => {
    const joined = planRoles(null, '', true)
    expect(joined[joined.indexOf('cleaner') + 1]).toBe('merge')
    expect(roleBand('merge')).toBe('data')
    expect(planRoles(null, '')).not.toContain('merge')
  })
  it('reads English and Arabic calculation tables without extracting unrelated tables', () => {
    const en = '| Figure | Value | Method |\n| --- | --- | --- |\n| revenue | 12 | recorded sum |\n\n| Person | Team | Note |\n| a | b | c |'
    const ar = '| الرقم | القيمة | الطريقة |\n| --- | --- | --- |\n| revenue | 12 | recorded sum |'
    expect(reportCalculations(en)).toEqual([{ name: 'revenue', value: '12', method: 'recorded sum' }])
    expect(reportCalculations(ar)).toEqual(reportCalculations(en))
    expect(reportCalculations('Report pending')).toEqual([])
  })
})
