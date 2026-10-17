import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backoff, liveConnection, parseEvents, resetLive } from '../features/live/live'
import type { LiveChange } from '../features/live/live'

function streamOf(...parts: string[]) {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part))
      controller.close()
    },
  })
}

const READY = 'retry: 3000\n\nid: 2026-10-17T09:00:00.000000+00:00~run~0\nevent: ready\ndata: {"kind":"ready"}\n\n'
const RUN =
  'id: 2026-10-17T09:00:01.000000+00:00~run~abc\nevent: run\n' +
  'data: {"kind":"run","id":"abc","state":"awaiting_approval","goal":"g","connector_id":"k1","created_at":"x","updated_at":"y"}\n\n'

describe('parseEvents', () => {
  it('reads complete events and keeps the rest for later', () => {
    const { events, rest } = parseEvents(': keep-alive\r\n\r\n' + READY + 'id: 1\nevent: run\ndata: {"a"')
    expect(events).toEqual([{ id: '2026-10-17T09:00:00.000000+00:00~run~0', event: 'ready', data: '{"kind":"ready"}' }])
    expect(rest).toBe('id: 1\nevent: run\ndata: {"a"')
  })

  it('joins data lines and defaults the event name', () => {
    expect(parseEvents('data: one\ndata: two\n\n').events).toEqual([{ id: undefined, event: 'message', data: 'one\ntwo' }])
  })
})

describe('backoff', () => {
  it('doubles from a second, randomised, up to thirty seconds', () => {
    expect(backoff(1, () => 0)).toBe(500)
    expect(backoff(1, () => 1)).toBe(1000)
    expect(backoff(3, () => 1)).toBe(4000)
    expect(backoff(12, () => 0)).toBe(15000)
    expect(backoff(12, () => 1)).toBe(30000)
  })
})

describe('the live connection', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetLive()
  })
  afterEach(() => {
    resetLive()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('delivers changes, then resumes from the last event when the stream ends', async () => {
    const headers: Array<Record<string, string>> = []
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      headers.push({ ...(init?.headers as Record<string, string>) })
      if (headers.length === 1) return new Response(streamOf(READY, RUN), { status: 200 })
      return new Response(new ReadableStream(), { status: 200 }) // stays open
    })
    const connection = liveConnection(fetcher as unknown as typeof fetch)
    const seen: LiveChange[] = []
    const stop = connection.listen((change) => seen.push(change))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    expect(seen).toEqual([expect.objectContaining({ kind: 'run', id: 'abc', state: 'awaiting_approval' })])
    expect(connection.status).toBe('live')
    expect(headers[0]['Last-Event-ID']).toBeUndefined()
    expect(headers[1]['Last-Event-ID']).toBe('2026-10-17T09:00:01.000000+00:00~run~abc')
    stop()
  })

  it('says it is reconnecting after an error, and tries again after a wait', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(new Response(streamOf(READY), { status: 200 }))
      .mockResolvedValue(new Response(new ReadableStream(), { status: 200 }))
    const connection = liveConnection(fetcher as unknown as typeof fetch)
    const statuses: string[] = []
    connection.watch(() => statuses.push(connection.status))
    const stop = connection.listen(() => undefined)
    await vi.waitFor(() => expect(connection.status).toBe('reconnecting'))
    expect(fetcher).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.waitFor(() => expect(connection.status).toBe('live'))
    expect(statuses).toEqual(['reconnecting', 'live'])
    stop()
  })

  it('is offline while the browser is, and reconnects when it comes back', async () => {
    const fetcher = vi.fn(async () => new Response(new ReadableStream(), { status: 200 }))
    const connection = liveConnection(fetcher as unknown as typeof fetch)
    const stop = connection.listen(() => undefined)
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    window.dispatchEvent(new Event('offline'))
    expect(connection.status).toBe('offline')
    window.dispatchEvent(new Event('online'))
    expect(connection.status).toBe('reconnecting')
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    stop()
  })

  it('closes when the last listener leaves', async () => {
    let signal: AbortSignal | undefined
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal ?? undefined
      return new Response(new ReadableStream(), { status: 200 })
    })
    const connection = liveConnection(fetcher as unknown as typeof fetch)
    const first = connection.listen(() => undefined)
    const second = connection.listen(() => undefined)
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    first()
    expect(signal?.aborted).toBe(false)
    second()
    expect(signal?.aborted).toBe(true)
  })
})
