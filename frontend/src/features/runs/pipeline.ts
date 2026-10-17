import type { Pipelines, RunTask } from '../../shared/types'

export const BANDS = ['data', 'analytics', 'assurance', 'publish'] as const
export type Band = typeof BANDS[number]
export const BASE_ROLES = [
  'planner', 'collector', 'contract', 'profiler', 'quality', 'privacy', 'cleaner',
  'governance', 'preparer', 'segments', 'descriptive', 'diagnostic', 'experiment',
  'predictive', 'anomaly', 'prescriptive', 'sensitivity', 'visuals', 'lineage',
  'validator', 'reporter', 'publish',
] as const

export function roleBand(role: string, pipelines?: Pipelines | null): Band {
  if (role === 'publish') return 'publish'
  if (['visuals', 'lineage', 'validator', 'reporter'].includes(role)) return 'assurance'
  if (['descriptive', 'diagnostic', 'experiment', 'predictive', 'anomaly', 'prescriptive', 'sensitivity'].includes(role)) return 'analytics'
  const custom = pipelines?.stages.find((stage) => stage.role === role)
  return custom && custom.after !== role ? roleBand(custom.after) : 'data'
}

/** The stages a run will have. A run that joins datasets merges them
 *  right after cleaning (ADR 0030). */
export function planRoles(pipelines: Pipelines | null, profile: string, joined = false): string[] {
  const custom = pipelines ? (profile ? pipelines.profiles[profile] ?? [] : pipelines.default) : []
  return BASE_ROLES.flatMap((role) => [
    role,
    ...(joined && role === 'cleaner' ? ['merge'] : []),
    ...custom.filter((name) => pipelines?.stages.find((stage) => stage.role === name)?.after === role),
  ])
}

export function groupedTasks(tasks: RunTask[], pipelines?: Pipelines | null) {
  return BANDS.map((band) => ({ band, tasks: tasks.filter((task) => roleBand(task.role, pipelines) === band) }))
}
