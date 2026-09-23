import type { MessageKey, Vars } from '../i18n'

export interface TranscriptEntry {
  id: number
  role: 'user' | 'agent'
  text: string
  time: string
}

export interface CommandInfo {
  command: string
  usage: string
  description: string
}

export type PreferenceValue = string | boolean

export interface SessionState {
  session_id: string
  agent_name: string
  version: string
  welcome: string
  ended: boolean
  created_at: string
  transcript: TranscriptEntry[]
  preferences: Record<string, PreferenceValue>
  memory: Record<string, string>
  memory_entries: MemoryEntry[]
  history: string[]
  memory_persisted: boolean
  commands: CommandInfo[]
}

export interface MemoryEntry {
  key: string
  text: string
  category: string
  updated: string | null
}

export interface ExportPayload {
  exported_at: string
  agent_name: string
  preferences: Record<string, PreferenceValue>
  memory: Record<string, string>
  memory_entries: MemoryEntry[]
  history: string[]
  transcript: TranscriptEntry[]
}

export type ActivityKind = 'info' | 'success' | 'error'

/** An activity event records *what happened* as a message code, not as a
 *  sentence, so the timeline reads in whichever language the interface
 *  is in when it is looked at — including after a switch. `detail` is
 *  free text (a server reply, a filename) and stays as it came. */
export interface ActivityEvent {
  id: number
  code: MessageKey
  vars?: Vars
  detail?: string
  kind: ActivityKind
  time: string
}

export type ConnectionStatus = 'ready' | 'working' | 'offline' | 'error' | 'ended'

export interface AuthConfig {
  mode: 'local' | 'jwt'
  provider?: string
  provider_url: string
  publishable_key: string
  flows: string[]
}

export interface IdentityInfo {
  mode: string
  principal: {
    subject: string
    role: string
    provider: string
    email: string
    permissions: string[]
  }
}

export type RunState =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'partially_completed'
  | 'failed'
  | 'cancelled'

export interface RunTask {
  id: string
  role: string
  title: string
  state: string
  summary: string | null
  quality_checks: Array<{ name: string; passed: boolean; detail: string }>
  claims: Array<{ id: string; text: string; type: string; evidence: string[]; status: string }>
}

export interface RunApproval {
  id: string
  action: string
  target: string
  risk: string
  impact: string
  reversibility: string
  state: string
  created_at: string
  decided_at: string | null
}

export interface ChartSpec {
  id: string
  type: 'bar' | 'line'
  title: string
  labels: string[]
  values: number[]
  alt: string
}

export interface RunDetail {
  id: string
  goal: string
  dataset_name: string
  state: RunState
  error: string | null
  created_at: string
  updated_at: string
  /** Server-side pause: honoured by clients and background workers alike. */
  paused: boolean
  tasks: RunTask[]
  /** One report per business-analytics type, in maturity-ladder order. */
  reports: {
    type: string
    question: string
    title: string
    /** One sentence in business language: the answer to this type's question. */
    headline: string
    content: string
  }[]
  approvals: RunApproval[]
  charts: ChartSpec[]
  report: {
    id: string
    name: string
    version: number
    content: string
    published_path: string | null
  } | null
}

export interface RunSummary {
  id: string
  goal: string
  dataset_name: string
  state: RunState
  created_at: string
  updated_at: string
}

/** What this tenant has used against its limits, from GET /api/usage. */
export interface UsageAllowance {
  used: number
  limit: number
  remaining: number
  resets_at?: string
}

export interface Usage {
  runs_today: UsageAllowance
  datasets: UsageAllowance
  dataset_bytes: UsageAllowance
  /** Real costs the system does not measure — named, not hidden. */
  not_tracked: string[]
}
