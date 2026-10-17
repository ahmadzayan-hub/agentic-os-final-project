import type { MessageKey, Vars } from '../i18n'

export interface TranscriptEntry {
  id: number
  role: 'user' | 'agent'
  text: string
  time: string
  /** Who understood an agent reply: a slash command, the rules, a
   *  model (then `provider` names it), or an agent runtime (then
   *  `provider` names it and `steps` lists what it called). Absent on
   *  user turns. */
  source?: 'command' | 'rules' | 'model' | 'runtime'
  provider?: string
  /** The action the reply took, e.g. `start_run`, and what it produced. */
  action?: string
  result?: { run_id?: string } | null
  steps?: TranscriptStep[]
}

/** One tool call an agent runtime made for a message: what it asked
 *  for, whether it was allowed, and the tool's own text. */
export interface TranscriptStep {
  tool: string
  arguments: Record<string, unknown>
  ok: boolean
  text: string
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
  /** Index of the first forecast point on a history-and-forecast line;
   *  absent on charts that are all measurement. */
  forecast_from?: number
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
  /** The language the run's reports are written in, fixed when it was
   *  created (ADR 0022). Runs from before reports had a language are 'en'. */
  report_language: 'en' | 'ar'
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
  /** What each model found, against its baseline (ADR 0033). */
  models?: ModelCard[]
  /** The live source a refresh made this run from (ADR 0034). */
  connector_id?: string | null
  /** Other datasets joined onto this one (ADR 0030); empty for one dataset. */
  joins?: Array<Pick<JoinSpec, 'dataset_id' | 'keys' | 'how'> & { alias: string }>
  breakdown?: string | null
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

/** A dataset stored for this owner, from GET /api/datasets: the newest
 *  50, content-addressed, so an identical file appears once. */
export interface DatasetSummary {
  id: string
  sha256: string
  name: string
  byte_size: number
  created_at: string
  /** csv, tsv, xlsx, json, jsonl or sample (ADR 0024); null for a
   *  dataset stored before formats were recorded. */
  source_format?: string | null
  row_count?: number | null
  column_count?: number | null
  /** True once the owner has saved a column mapping (ADR 0025). */
  mapped?: boolean
  mapping_updated_at?: string | null
}

/** What a column is, in a mapping (ADR 0025). */
export type ColumnRole = 'measure' | 'dimension' | 'date' | 'ignore'
export type DateOrder = 'auto' | 'day-first' | 'month-first'
export type Grain = 'auto' | 'day' | 'month' | 'quarter' | 'year'

/** A column mapping: one role per column, the measure analysed, the
 *  breakdown, and how dates are read and summed. */
export interface ColumnMapping {
  roles: Record<string, ColumnRole>
  measure: string | null
  dimension: string | null
  date_order: DateOrder
  grain: Grain
  version?: number
}

/** What the server read in one column, and the role it suggests. */
export interface ColumnProfile {
  name: string
  type: 'number' | 'date' | 'text' | 'empty'
  filled: number
  cells: number
  numeric_share: number
  date_share: number
  distinct: number
  examples: string[]
  ambiguous_order: boolean
  suggested_role: ColumnRole
  /** Why the role is suggested, in the reader's language. */
  reason: string
}

/** GET /api/datasets/{id}: everything the mapping step shows. */
export interface DatasetDetail {
  dataset: DatasetSummary
  columns: ColumnProfile[]
  preview: string[][]
  row_count: number
  /** The suggestion reads an even sample of a large table. */
  profiled_rows: number
  mapping: ColumnMapping | null
  suggestion: ColumnMapping
}

/** One reason a mapping or a join was refused, named by its field and
 *  column; a join's problems also say which join (ADR 0030). */
export interface MappingProblem {
  field:
    | 'roles' | 'measure' | 'dimension' | 'date_order' | 'grain'
    | 'joins' | 'keys' | 'how' | 'alias' | 'breakdown' | 'dataset'
  column: string | null
  message: string
  join?: number | null
}

/** One key of a join: a column of the table so far and the column of the
 *  joined dataset that holds the same values (ADR 0030). */
export interface JoinKey {
  left: string
  right: string
}

/** A dataset joined onto a run's main dataset. `left` keeps every row;
 *  `inner` keeps only the rows that found a match. */
export interface JoinSpec {
  dataset_id: string
  keys: JoinKey[]
  how: 'left' | 'inner'
  alias?: string | null
}

/** What one join did: rows in and out, matches, and the columns it added. */
export interface JoinRecord {
  dataset_id: string
  name: string
  alias: string
  how: 'left' | 'inner'
  keys: JoinKey[]
  rows_in: number
  rows_out: number
  matched: number
  unmatched: number
  coverage: number
  unmatched_keys: string[]
  lookup_rows: number
  lookup_unused: number
  added_columns: string[]
  renamed: Record<string, string>
}

/** POST /api/joins/preview: the merge a run would make, without the run. */
export interface JoinPreview {
  rows_before: number
  rows_after: number
  columns: string[]
  added_columns: string[]
  breakdown_choices: string[]
  joins: JoinRecord[]
  personal_data: Array<{ dataset: string; column: string }>
  preview: string[][]
}

/** What POST /api/datasets read from a file. `created` is false when the
 *  same data was already stored, which costs nothing. */
export interface UploadResult {
  dataset: DatasetSummary
  created: boolean
  columns: string[]
  preview: string[][]
  warnings: string[]
  sheets: string[]
}

/** Registered custom stages and the profiles that choose among them,
 *  from GET /api/pipelines (ADR 0020). */
export interface Pipelines {
  stages: Array<{
    role: string
    title: string
    after: string
    question: string | null
    can_fail_run: boolean
  }>
  profiles: Record<string, string[]>
  /** The custom stages a run gets when no profile is chosen. */
  default: string[]
  problems: string[]
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

/** A column of a run's cleaned table, from GET /api/runs/{id}/fields
 *  (ADR 0031): its type, its part in the run, and what a filter offers. */
export interface TableField {
  name: string
  type: 'number' | 'text'
  role: 'analysed' | 'measure' | 'breakdown' | 'date' | 'joined' | null
  filled: number
  records: number
  min?: number | null
  max?: number | null
  distinct?: number
  /** Present for text with at most 200 distinct values, sorted. */
  values?: string[]
}

export type FilterOp =
  | 'eq' | 'ne' | 'in' | 'not_in' | 'gt' | 'gte' | 'lt' | 'lte' | 'between' | 'empty' | 'not_empty'

export interface TableFilter {
  column: string
  op: FilterOp
  value?: string | number
  values?: Array<string | number>
}

/** One aggregate. A ratio is the sum of the numerator over the sum of the
 *  denominator, never an average of row rates. */
export interface QueryMeasure {
  agg: 'sum' | 'mean' | 'min' | 'max' | 'count' | 'distinct' | 'ratio'
  column?: string
  numerator?: string
  denominator?: string
}

export interface QuerySpec {
  group_by?: Array<string | { column: string; bins: number }>
  measures: QueryMeasure[]
  filters?: TableFilter[]
  sort?: { by: string; desc?: boolean }
  limit?: number
}

/** A group's key: text, a number, a bin as [from, to), or null (empty). */
export type GroupKey = string | number | null | [number, number]

export interface QueryAnswer {
  group_by: Array<{ column: string; binned: boolean }>
  measures: Array<QueryMeasure & { key: string }>
  groups: Array<{ keys: GroupKey[]; records: number; values: Array<number | null> }>
  group_count: number
  truncated: boolean
  matched_records: number
  records: number
}

export interface RecordsSpec {
  filters?: TableFilter[]
  sort?: { by: string; desc?: boolean }
  offset?: number
  limit?: number
  sample?: number
}

export interface RecordsPage {
  columns: string[]
  rows: Array<Array<string | number | null>>
  total: number
  offset?: number
  limit?: number
  sampled?: boolean
}

/** A model's card (ADR 0033): what it predicts, from what, how it was
 *  tested, and how it did against the plain baseline it must beat. */
export interface ModelCard {
  role: string
  title: string
  kind: 'regression' | 'classification' | 'clustering' | 'seasonal'
  target: string
  inputs: string[]
  train_records: number
  test_records: number
  split: { kind: 'time' | 'every_fifth' | 'last_season' | 'none'; first_held_out?: string }
  metric: {
    name: 'average_error' | 'balanced_accuracy' | 'separation'
    model: number
    baseline: number
    baseline_name: string
  }
  improvement: number
  beats_baseline: boolean
  details: Record<string, unknown>
}
