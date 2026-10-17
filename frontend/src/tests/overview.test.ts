import { describe, expect, it } from 'vitest'
import {
  countRuns,
  latestWithFindings,
  recentRuns,
  RUN_PAGE,
  waitingForApproval,
} from '../features/overview/summary'
import { formatBytes } from '../shared/format'
import type { RunState, RunSummary } from '../shared/types'

function run(id: string, state: RunState, created: string, updated = created): RunSummary {
  return {
    id,
    goal: `goal ${id}`,
    dataset_name: 'sample sales dataset',
    state,
    created_at: `2026-10-${created}T09:00:00+00:00`,
    updated_at: `2026-10-${updated}T09:00:00+00:00`,
  }
}

const RUNS = [
  run('a', 'completed', '10', '11'),
  run('b', 'awaiting_approval', '12'),
  run('c', 'partially_completed', '09', '13'),
  run('d', 'running', '14'),
  run('e', 'awaiting_approval', '08'),
  run('f', 'failed', '15'),
]

describe('overview summary', () => {
  it('counts finished, waiting and active runs, and says when the page may be cut off', () => {
    expect(countRuns(RUNS)).toEqual({ finished: 2, waiting: 2, active: 1, capped: false })
    const full = Array.from({ length: RUN_PAGE }, (_, n) => run(String(n), 'completed', '10'))
    expect(countRuns(full).capped).toBe(true)
    expect(countRuns([])).toEqual({ finished: 0, waiting: 0, active: 0, capped: false })
  })

  it('takes findings from the most recently updated run that has reports', () => {
    // c finished last (13th); the running and failed runs have no reports.
    expect(latestWithFindings(RUNS)?.id).toBe('c')
    expect(latestWithFindings([run('x', 'failed', '01'), run('y', 'queued', '02')])).toBeNull()
  })

  it('lists the runs at the approval gate longest wait first', () => {
    expect(waitingForApproval(RUNS).map((r) => r.id)).toEqual(['e', 'b'])
  })

  it('lists recent runs by last update, newest first, up to the limit', () => {
    expect(recentRuns(RUNS, 3).map((r) => r.id)).toEqual(['f', 'd', 'c'])
    // The input order is left alone.
    expect(RUNS[0].id).toBe('a')
  })
})

describe('formatBytes', () => {
  const plain = (value: number, options?: Intl.NumberFormatOptions) =>
    new Intl.NumberFormat('en', options).format(value)

  it('uses decimal units with Latin symbols', () => {
    expect(formatBytes(512, plain)).toBe('512 B')
    expect(formatBytes(48_250, plain)).toBe('48.3 kB')
    expect(formatBytes(2_000_000, plain)).toBe('2 MB')
  })
})
