/** Live sources (ADR 0034): the connector API. Lives with the views that
 *  use it, so the first load does not carry it. */
import { request } from '../../shared/api'

export interface Connector {
  id: string
  name: string
  url: string
  format: string | null
  sheet: string | null
  every_minutes: number | null
  goal: string
  language: 'en' | 'ar'
  profile: string | null
  enabled: boolean
  last_status: 'updated' | 'unchanged' | 'failed' | null
  last_error: string | null
  last_checked_at: string | null
  last_dataset_id: string | null
  last_run_id: string | null
  next_due_at: string | null
  failures: number
  created_at: string
  updated_at: string
}

export interface ConnectorIn {
  name: string
  url: string
  goal: string
  format?: string | null
  every_minutes?: number | null
  language: 'en' | 'ar'
}

export interface RefreshResult {
  connector: Connector
  status: 'updated' | 'unchanged' | 'failed'
  error: string | null
  dataset: string | null
  run: string | null
  note: string | null
}

/** A fetch takes up to 15 seconds, then the file is read and stored. */
const REFRESH_TIMEOUT_MS = 45_000

export const connectorsApi = {
  list: () => request<{ connectors: Connector[] }>('/api/connectors'),
  create: (body: ConnectorIn) =>
    request<Connector>(`/api/connectors?language=${body.language}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  update: (id: string, body: { enabled?: boolean; every_minutes?: number | null }, language: string) =>
    request<Connector>(`/api/connectors/${encodeURIComponent(id)}?language=${language}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    request<null>(`/api/connectors/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  refresh: (id: string, language: string) =>
    request<RefreshResult>(
      `/api/connectors/${encodeURIComponent(id)}/refresh?language=${language}`,
      { method: 'POST' },
      REFRESH_TIMEOUT_MS,
    ),
}
