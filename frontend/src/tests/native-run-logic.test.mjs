// Dependency-free checks for environments without the frontend packages.
// The full Vitest and browser suites remain the release gates.
import test from 'node:test'
import assert from 'node:assert/strict'
import { snapshotEvents, appendEvents } from '../features/runs/runEvents.ts'
import { planRoles, roleBand } from '../features/runs/pipeline.ts'
import { reportCalculations } from '../features/runs/evidence.ts'
import { runFixture } from './run-fixture.ts'

test('snapshots do not invent intermediate execution', () => {
  const first = runFixture()
  const next = runFixture({ state: 'running', updated_at: '2026-10-16T10:01:00Z', tasks: [{ ...first.tasks[0], state: 'succeeded' }] })
  assert.deepEqual(snapshotEvents(first, next).filter(e => e.kind === 'stage.changed').map(e => e.state), ['succeeded'])
  assert.deepEqual(snapshotEvents(next, next), [])
})
test('pause, cancel and approval remain distinct observations', () => {
  assert(snapshotEvents(runFixture(), runFixture({ paused: true })).some(e => e.kind === 'run.paused'))
  assert(snapshotEvents(runFixture(), runFixture({ state: 'cancelled' })).some(e => e.kind === 'run.finished' && e.state === 'cancelled'))
  const next = runFixture({ state: 'awaiting_approval', approvals: [{ id: 'test', state: 'pending' }] })
  assert(snapshotEvents(runFixture(), next).some(e => e.kind === 'approval.requested'))
  assert(!snapshotEvents(runFixture(), next).some(e => e.kind === 'artifact.published'))
})
test('observation history is deduplicated and bounded', () => {
  const event = snapshotEvents(null, runFixture())[0]
  assert.equal(appendEvents([], [event, event]).length, 1)
  assert.equal(appendEvents([], Array.from({ length: 150 }, (_, i) => ({ ...event, id: String(i) }))).length, 120)
})
test('custom profiles preserve stage placement and publish last', () => {
  const p = { stages: [{ role: 'custom', after: 'predictive' }], profiles: { custom: ['custom'] }, default: [] }
  const roles = planRoles(p, 'custom')
  assert.equal(roles[roles.indexOf('predictive') + 1], 'custom')
  assert.equal(roleBand('custom', p), 'analytics')
  assert.equal(roles.at(-1), 'publish')
})
test('receipt tables retain report values without guessing reference IDs', () => {
  assert.deepEqual(reportCalculations('| Figure | Value | Method |\n| --- | --- | --- |\n| synthetic | 12 | recorded sum |'), [{ name: 'synthetic', value: '12', method: 'recorded sum' }])
  assert.deepEqual(reportCalculations('| Name | Value | Note |\n| x | 12 | y |'), [])
  assert.deepEqual(reportCalculations('| المؤشر | القيمة | الطريقة |\n| --- | --- | --- |\n| مثال | 12 | الجمع |'), [{ name: 'مثال', value: '12', method: 'الجمع' }])
})
