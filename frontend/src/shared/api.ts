import { translate } from '../i18n'
import type {
  AuthConfig,
  ExportPayload,
  IdentityInfo,
  Pipelines,
  RunDetail,
  RunSummary,
  SessionState,
  TranscriptEntry,
  Usage,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const REQUEST_TIMEOUT_MS = 10_000

export class ApiError extends Error {
  status: number
  offline: boolean

  constructor(message: string, status = 0, offline = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.offline = offline
  }
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
function authHeaders(): Record<string, string> {
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      ...init,
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
    const detail =
      body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
        ? body.detail
        : translate('api.failed', { status: response.status })
    throw new ApiError(detail, response.status)
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
  createRun: (goal: string, datasetText?: string, datasetName?: string, profile?: string) =>
    request<RunDetail>('/api/runs', {
      method: 'POST',
      body: JSON.stringify({
        goal,
        dataset_text: datasetText ?? null,
        dataset_name: datasetName ?? null,
        profile: profile || null,
      }),
    }),
  pipelines: () => request<Pipelines>('/api/pipelines'),
  listRuns: () => request<{ runs: RunSummary[] }>('/api/runs'),
  usage: () => request<Usage>('/api/usage'),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  advanceRun: (id: string) => request<RunDetail>(`/api/runs/${id}/advance`, { method: 'POST' }),
  pauseRun: (id: string) => request<RunDetail>(`/api/runs/${id}/pause`, { method: 'POST' }),
  resumeRun: (id: string) => request<RunDetail>(`/api/runs/${id}/resume`, { method: 'POST' }),
  cancelRun: (id: string) => request<RunDetail>(`/api/runs/${id}/cancel`, { method: 'POST' }),
  decideApproval: (id: string, approvalId: string, decision: 'approve' | 'reject') =>
    request<RunDetail>(`/api/runs/${id}/approvals/${approvalId}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
}
