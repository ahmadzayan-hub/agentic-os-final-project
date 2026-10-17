import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../shared/api'

function mockFetchOnce(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const impl = {
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
    ...response,
  } as Response
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(impl))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('returns parsed JSON for successful requests', async () => {
    mockFetchOnce({ json: () => Promise.resolve({ status: 'ok', agent_name: 'A', version: '1' }) })
    const result = await api.health()
    expect(result.status).toBe('ok')
  })

  it('surfaces the server "detail" message on API errors', async () => {
    mockFetchOnce({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: 'This session has ended.' }),
    })
    await expect(api.sendMessage('sid', 'hello')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      message: 'This session has ended.',
    })
  })

  it('maps network failures to a friendly offline error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    try {
      await api.health()
      expect.unreachable('health() should have thrown')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).offline).toBe(true)
      expect((error as ApiError).message).toMatch(/Cannot reach/)
    }
  })

  it('falls back to a status message when the error body is not JSON', async () => {
    mockFetchOnce({ ok: false, status: 500, json: () => Promise.reject(new Error('not json')) })
    await expect(api.health()).rejects.toMatchObject({ message: 'Request failed (500).' })
  })

  it('analyses a stored dataset by its id and sends no file text', async () => {
    mockFetchOnce({ json: () => Promise.resolve({ id: 'r1' }) })
    await api.createRun('Analyse it', 'a,b\n1,2', 'local.csv', undefined, 'ar', 'ds1')
    const [path, init] = vi.mocked(fetch).mock.calls[0]
    expect(path).toBe('/api/runs')
    expect(JSON.parse(String(init?.body))).toEqual({
      goal: 'Analyse it',
      dataset_text: null,
      dataset_name: null,
      dataset_id: 'ds1',
      profile: null,
      language: 'ar',
      joins: null,
      breakdown: null,
    })
  })

  it('sends joins and their breakdown with a stored dataset (ADR 0030)', async () => {
    mockFetchOnce({ json: () => Promise.resolve({ id: 'r1' }) })
    const joins = [{ dataset_id: 'ds2', keys: [{ left: 'item', right: 'code' }], how: 'left' as const }]
    await api.createRun('Analyse it', undefined, undefined, undefined, 'en', 'ds1', { joins, breakdown: 'family' })
    const body = JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))
    expect(body.joins).toEqual(joins)
    expect(body.breakdown).toBe('family')
    mockFetchOnce({ json: () => Promise.resolve({ rows_before: 1 }) })
    await api.previewJoins('ds1', joins, null, 'ar')
    // Each mock is a fresh fetch, so the preview is its first call.
    const [path, init] = vi.mocked(fetch).mock.calls[0]
    expect(path).toBe('/api/joins/preview?language=ar')
    expect(JSON.parse(String(init?.body))).toEqual({ dataset_id: 'ds1', joins, breakdown: null })
  })

  it('downloads the cleaned table with the token and the server\'s file name (ADR 0031)', async () => {
    localStorage.setItem('aos-token', 'tok')
    mockFetchOnce({
      blob: () => Promise.resolve(new Blob(['a,b'])),
      headers: new Headers({ 'content-disposition': 'attachment; filename="sales-r1-cleaned.csv"' }),
    })
    const { name, blob } = await api.downloadTable('r1', 'ar')
    const [path, init] = vi.mocked(fetch).mock.calls[0]
    expect(path).toBe('/api/runs/r1/data.csv?language=ar')
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    expect(name).toBe('sales-r1-cleaned.csv')
    expect(await blob.text()).toBe('a,b')
    localStorage.removeItem('aos-token')
  })

  it('uploads a file as the request body, named and in the reader\'s language', async () => {
    localStorage.setItem('aos-token', 'tok')
    mockFetchOnce({ status: 201, json: () => Promise.resolve({ created: true }) })
    const file = new File(['a,b\n1,2\n'], 'ventes été.csv', { type: 'text/csv' })
    await api.uploadDataset(file, 'ar')
    const [path, init] = vi.mocked(fetch).mock.calls[0]
    expect(path).toBe('/api/datasets?name=ventes%20%C3%A9t%C3%A9.csv&language=ar')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(file)
    // The file's own type replaces JSON, and the token is still sent.
    expect(init?.headers).toMatchObject({ 'Content-Type': 'text/csv', Authorization: 'Bearer tok' })
    localStorage.removeItem('aos-token')
  })

  it('lists the stored datasets', async () => {
    mockFetchOnce({ json: () => Promise.resolve({ datasets: [] }) })
    await expect(api.listDatasets()).resolves.toEqual({ datasets: [] })
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/datasets')
  })
})
