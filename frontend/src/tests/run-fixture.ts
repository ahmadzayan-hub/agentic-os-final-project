import type { RunDetail } from '../shared/types'

/** Synthetic state-machine fixture, never included in product content. */
export function runFixture(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'run-test', goal: 'Synthetic test analysis', dataset_name: 'synthetic.csv',
    state: 'queued', error: null, paused: false, report_language: 'en',
    created_at: '2026-10-16T10:00:00Z', updated_at: '2026-10-16T10:00:00Z',
    tasks: [{ id: 'stage-test', role: 'descriptive', title: 'Descriptive', state: 'pending', summary: null, quality_checks: [], claims: [] }],
    reports: [], approvals: [], charts: [], report: null,
    ...overrides,
  }
}
