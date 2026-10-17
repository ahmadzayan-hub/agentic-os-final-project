import { translate } from '../i18n'
import type {
  AuthConfig,
  ColumnMapping,
  DatasetDetail,
  DatasetSummary,
  ExportPayload,
  IdentityInfo,
  JoinPreview,
  JoinSpec,
  MappingProblem,
  Pipelines,
  QueryAnswer,
  QuerySpec,
  RecordsPage,
  RecordsSpec,
  RunDetail,
  RunSummary,
  SessionState,
  TableField,
  TranscriptEntry,
  UploadResult,
  Usage,
} from './types'

export const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const REQUEST_TIMEOUT_MS = 10_000
// A 4 MB file on a slow connection, then read on the server.
const UPLOAD_TIMEOUT_MS = 60_000

/** The most one upload can be (server/datasets.py, ADR 0024). Checked
 *  here only to save a wasted transfer; the server decides. */
export const MAX_UPLOAD_BYTES = 4_000_000

export class ApiError extends Error {
  status: number
  offline: boolean
  /** Field-level reasons, when the server gives them (a refused mapping). */
  problems: MappingProblem[]

  constructor(message: string, status = 0, offline = false, problems: MappingProblem[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.offline = offline
    this.problems = problems
  }
}

/** The server's `detail`: a sentence, or a summary with field errors. */
function readDetail(body: unknown): { message: string | null; problems: MappingProblem[] } {
  if (!body || typeof body !== 'object' || !('detail' in body)) return { message: null, problems: [] }
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') return { message: detail, problems: [] }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const { message, errors } = detail as { message: unknown; errors?: unknown }
    return {
      message: typeof message === 'string' ? message : null,
      problems: Array.isArray(errors) ? (errors as MappingProblem[]) : [],
    }
  }
  return { message: null, problems: [] }
}

export const TOKEN_KEY = 'aos-token'

export function storeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode — the token lives for this page only */
  }
}

export function hasToken(): boolean {
  try {
    return Boolean(localStorage.getItem(TOKEN_KEY))
  } catch {
    return false
  }
}

/** Bearer token for hosted deployments that enable managed auth. In
 *  local mode none exists and the header is simply omitted. */
export function authHeaders(): Record<string, string> {
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  const { headers, ...rest } = init
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      // A caller's headers add to these; the token is never dropped.
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
        ...(headers as Record<string, string> | undefined),
      },
      signal: controller.signal,
    })
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === 'AbortError'
    // Transport failures are the one class of message this client
    // writes itself; everything else is the server's `detail`.
    throw new ApiError(
      timedOut ? translate('api.timeout') : translate('api.unreachable'),
      0,
      !timedOut,
    )
  } finally {
    clearTimeout(timer)
  }

  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    const { message, problems } = readDetail(body)
    throw new ApiError(
      message ?? translate('api.failed', { status: response.status }),
      response.status,
      false,
      problems,
    )
  }
  return body as T
}

export interface OperationResult {
  reply_text: string
  state: SessionState
}

export interface MessageResult {
  reply: TranscriptEntry
  state: SessionState
}

/** The file name a download was given, from Content-Disposition. */
function attachmentName(header: string | null, fallback: string): string {
  const match = header?.match(/filename="([^"]+)"/)
  return match ? match[1] : fallback
}

export const api = {
  health: () => request<{ status: string; agent_name: string; version: string }>('/api/health'),
  authConfig: () => request<AuthConfig>('/api/auth/config'),
  identity: () => request<IdentityInfo>('/api/identity'),
  /** `language` seeds the agent's own reply language so the welcome
   *  message and command descriptions arrive in the reader's language
   *  from the first response, with no second request to correct them. */
  createSession: (language?: string) =>
    request<SessionState>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ language: language ?? null }),
    }),
  getSession: (id: string) => request<SessionState>(`/api/sessions/${id}`),
  endSession: (id: string) => request<SessionState>(`/api/sessions/${id}`, { method: 'DELETE' }),
  sendMessage: (id: string, text: string) =>
    request<MessageResult>(`/api/sessions/${id}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  clearHistory: (id: string) =>
    request<OperationResult>(`/api/sessions/${id}/history`, { method: 'DELETE' }),
  setPreference: (id: string, key: string, value: string) =>
    request<OperationResult>(`/api/sessions/${id}/preferences`, {
      method: 'PUT',
      body: JSON.stringify({ key, value }),
    }),
  addMemory: (id: string, information: string, category?: string) =>
    request<OperationResult>(`/api/sessions/${id}/memory`, {
      method: 'POST',
      body: JSON.stringify({ information, category: category ?? null }),
    }),
  updateMemory: (id: string, key: string, information: string, category?: string) =>
    request<OperationResult>(`/api/sessions/${id}/memory/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ information, category: category ?? null }),
    }),
  deleteMemory: (id: string, key: string) =>
    request<OperationResult>(`/api/sessions/${id}/memory/${encodeURIComponent(key)}`, {
      method: 'DELETE',
    }),
  exportData: (id: string) => request<ExportPayload>(`/api/sessions/${id}/export`),
  clearMemory: (id: string) =>
    request<OperationResult>(`/api/sessions/${id}/memory`, { method: 'DELETE' }),
  /** `datasetId` analyses a dataset already stored for this owner, so a
   *  file is never sent twice; it takes the place of `datasetText`. */
  createRun: (
    goal: string,
    datasetText?: string,
    datasetName?: string,
    profile?: string,
    language: 'en' | 'ar' = 'en',
    datasetId?: string,
    /** Other stored datasets joined onto this one, and a breakdown from
     *  the merged table (ADR 0030). The server checks the merge first. */
    merge?: { joins: JoinSpec[]; breakdown?: string | null },
  ) =>
    request<RunDetail>(
      '/api/runs',
      {
        method: 'POST',
        body: JSON.stringify({
          goal,
          dataset_text: datasetId ? null : (datasetText ?? null),
          dataset_name: datasetId ? null : (datasetName ?? null),
          dataset_id: datasetId ?? null,
          profile: profile || null,
          language,
          joins: merge?.joins.length ? merge.joins : null,
          breakdown: merge?.joins.length ? (merge.breakdown || null) : null,
        }),
      },
      merge?.joins.length ? UPLOAD_TIMEOUT_MS : REQUEST_TIMEOUT_MS,
    ),
  /** The merge a run with these joins would make, refused with every
   *  problem by field when it cannot be made (ADR 0030). */
  previewJoins: (datasetId: string, joins: JoinSpec[], breakdown: string | null, language: 'en' | 'ar' = 'en') =>
    request<JoinPreview>(
      `/api/joins/preview?language=${language}`,
      { method: 'POST', body: JSON.stringify({ dataset_id: datasetId, joins, breakdown: breakdown || null }) },
      UPLOAD_TIMEOUT_MS,
    ),
  listDatasets: () => request<{ datasets: DatasetSummary[] }>('/api/datasets'),
  /** The file itself is the request body: CSV, TSV, Excel, JSON or JSON
   *  Lines. The server reads it, stores it once and answers in `language`. */
  uploadDataset: (file: File, language: 'en' | 'ar' = 'en') =>
    request<UploadResult>(
      `/api/datasets?name=${encodeURIComponent(file.name)}&language=${language}`,
      {
        method: 'POST',
        body: file,
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
      },
      UPLOAD_TIMEOUT_MS,
    ),
  /** Preview, column profile, saved mapping and a suggestion (ADR 0025). */
  getDataset: (id: string, language: 'en' | 'ar' = 'en') =>
    request<DatasetDetail>(`/api/datasets/${encodeURIComponent(id)}?language=${language}`, {}, UPLOAD_TIMEOUT_MS),
  /** Checked against every row; a refusal carries `problems` by field. */
  saveMapping: (id: string, mapping: ColumnMapping, language: 'en' | 'ar' = 'en') =>
    request<DatasetDetail>(
      `/api/datasets/${encodeURIComponent(id)}/mapping?language=${language}`,
      {
        method: 'PUT',
        body: JSON.stringify({
          roles: mapping.roles,
          measure: mapping.measure,
          dimension: mapping.dimension,
          date_order: mapping.date_order,
          grain: mapping.grain,
        }),
      },
      UPLOAD_TIMEOUT_MS,
    ),
  /** Back to automatic detection for runs from now on. */
  clearMapping: (id: string, language: 'en' | 'ar' = 'en') =>
    request<DatasetDetail>(
      `/api/datasets/${encodeURIComponent(id)}/mapping?language=${language}`,
      { method: 'DELETE' },
      UPLOAD_TIMEOUT_MS,
    ),
  pipelines: () => request<Pipelines>('/api/pipelines'),
  listRuns: () => request<{ runs: RunSummary[] }>('/api/runs'),
  usage: () => request<Usage>('/api/usage'),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  advanceRun: (id: string) => request<RunDetail>(`/api/runs/${id}/advance`, { method: 'POST' }),
  pauseRun: (id: string) => request<RunDetail>(`/api/runs/${id}/pause`, { method: 'POST' }),
  resumeRun: (id: string) => request<RunDetail>(`/api/runs/${id}/resume`, { method: 'POST' }),
  cancelRun: (id: string) => request<RunDetail>(`/api/runs/${id}/cancel`, { method: 'POST' }),
  /** A run's cleaned table (ADR 0031): fields, totals by group, rows. */
  tableFields: (id: string, language: 'en' | 'ar' = 'en') =>
    request<{ fields: TableField[]; records: number }>(
      `/api/runs/${encodeURIComponent(id)}/fields?language=${language}`, {}, UPLOAD_TIMEOUT_MS),
  queryTable: (id: string, spec: QuerySpec, language: 'en' | 'ar' = 'en') =>
    request<QueryAnswer>(
      `/api/runs/${encodeURIComponent(id)}/query?language=${language}`,
      { method: 'POST', body: JSON.stringify(spec) },
      UPLOAD_TIMEOUT_MS,
    ),
  tableRecords: (id: string, spec: RecordsSpec, language: 'en' | 'ar' = 'en') =>
    request<RecordsPage>(
      `/api/runs/${encodeURIComponent(id)}/records?language=${language}`,
      { method: 'POST', body: JSON.stringify(spec) },
      UPLOAD_TIMEOUT_MS,
    ),
  /** The cleaned table as a CSV file. Fetched with the token, which a
   *  plain link could not send, then handed to the browser to save. */
  downloadTable: async (id: string, language: 'en' | 'ar' = 'en') => {
    let response: Response
    try {
      response = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(id)}/data.csv?language=${language}`, {
        headers: authHeaders(),
      })
    } catch {
      throw new ApiError(translate('api.unreachable'), 0, true)
    }
    if (!response.ok) {
      let message: string | null = null
      try {
        message = readDetail(await response.json()).message
      } catch {
        message = null
      }
      throw new ApiError(message ?? translate('api.failed', { status: response.status }), response.status)
    }
    return {
      blob: await response.blob(),
      name: attachmentName(response.headers.get('content-disposition'), `run-${id}-cleaned.csv`),
    }
  },
  decideApproval: (id: string, approvalId: string, decision: 'approve' | 'reject') =>
    request<RunDetail>(`/api/runs/${id}/approvals/${approvalId}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
}
