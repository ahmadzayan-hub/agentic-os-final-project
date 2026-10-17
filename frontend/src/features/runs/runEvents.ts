import type { RunDetail } from '../../shared/types'

export type RunEventKind =
  | 'run.started' | 'run.changed' | 'run.paused' | 'run.resumed'
  | 'stage.changed' | 'approval.requested' | 'approval.decided'
  | 'artifact.published' | 'run.finished'

/** An observation of a server snapshot, not an SSE event or model thought. */
export interface RunEvent {
  id: string
  runId: string
  time: string
  kind: RunEventKind
  subject: string
  state: string
}

const FINISHED = new Set(['completed', 'partially_completed', 'failed', 'cancelled'])

export function snapshotEvents(previous: RunDetail | null, next: RunDetail): RunEvent[] {
  const events: RunEvent[] = []
  function add(kind: RunEventKind, subject: string, state: string) {
    events.push({
      id: `${next.id}:${next.updated_at}:${kind}:${subject}:${state}`,
      runId: next.id, time: next.updated_at, kind, subject, state,
    })
  }
  if (!previous) add('run.started', next.id, next.state)
  else if (previous.state !== next.state) add('run.changed', next.id, next.state)
  if (previous && previous.paused !== next.paused) {
    add(next.paused ? 'run.paused' : 'run.resumed', next.id, next.state)
  }
  for (const task of next.tasks) {
    const before = previous?.tasks.find((item) => item.id === task.id)
    if (before ? before.state !== task.state : task.state !== 'pending') {
      add('stage.changed', task.id, task.state)
    }
  }
  for (const approval of next.approvals) {
    const before = previous?.approvals.find((item) => item.id === approval.id)
    if (before?.state === approval.state) continue
    add(approval.state === 'pending' ? 'approval.requested' : 'approval.decided', approval.id, approval.state)
  }
  if (next.report?.published_path && next.report.published_path !== previous?.report?.published_path) {
    add('artifact.published', next.report.id, next.report.published_path)
  }
  if (FINISHED.has(next.state) && previous?.state !== next.state) add('run.finished', next.id, next.state)
  return events
}

export function appendEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const seen = new Set(current.map((event) => event.id))
  return [...current, ...incoming.filter((event) => {
    if (seen.has(event.id)) return false
    seen.add(event.id)
    return true
  })].slice(-120)
}
