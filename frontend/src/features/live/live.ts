/** Pushed updates (ADR 0034): the owner's event stream.
 *
 *  Read with fetch rather than EventSource, so the bearer token travels in
 *  a header as on every other request. The server ends each stream within
 *  a minute; the client reconnects at once with the last event's id and
 *  receives whatever it missed. After an error it waits a growing,
 *  randomised time up to 30 seconds, and says it is offline while the
 *  browser is. One connection serves every view that listens, and closes
 *  when the last one stops. */
import { useEffect, useRef, useSyncExternalStore } from 'react'
import { API_BASE, authHeaders } from '../../shared/api'

export type LiveStatus = 'connecting' | 'live' | 'reconnecting' | 'offline'

export interface RunChange {
  kind: 'run'
  id: string
  state: string
  goal: string
  connector_id: string | null
  created_at: string
  updated_at: string
}

export interface ConnectorChange {
  kind: 'connector'
  id: string
  name: string
  enabled: boolean
  last_status: 'updated' | 'unchanged' | 'failed' | null
  last_error: string | null
  last_run_id: string | null
  last_checked_at: string | null
  next_due_at: string | null
  updated_at: string
}

export type LiveChange = RunChange | ConnectorChange

export interface ServerEvent {
  id?: string
  event: string
  data: string
}

const MAX_WAIT_MS = 30_000

/** Complete events in `buffer`, and the incomplete rest to keep. */
export function parseEvents(buffer: string): { events: ServerEvent[]; rest: string } {
  const text = buffer.replace(/\r\n?/g, '\n')
  const blocks = text.split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: ServerEvent[] = []
  for (const block of blocks) {
    let id: string | undefined
    let name = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
      if (field === 'id') id = value
      else if (field === 'event') name = value
      else if (field === 'data') data.push(value)
    }
    if (data.length || id) events.push({ id, event: name, data: data.join('\n') })
  }
  return { events, rest }
}

/** How long to wait before attempt `n` (from 1): doubling from a second,
 *  capped at 30, and randomised so many pages do not return at once. */
export function backoff(attempt: number, random = Math.random): number {
  const ceiling = Math.min(MAX_WAIT_MS, 1000 * 2 ** Math.max(0, attempt - 1))
  return Math.round(ceiling / 2 + (random() * ceiling) / 2)
}

type Listener = (change: LiveChange) => void

class LiveConnection {
  status: LiveStatus = 'connecting'
  /** When the stream last answered: what the screen is up to date with. */
  lastContact: number | null = null
  private listeners = new Set<Listener>()
  private watchers = new Set<() => void>()
  private lastEventId: string | null = null
  private controller: AbortController | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private failures = 0
  private running = false

  constructor(private readonly fetcher: typeof fetch = (...args) => fetch(...args)) {}

  listen(listener: Listener) {
    this.listeners.add(listener)
    if (!this.running) this.start()
    return () => {
      this.listeners.delete(listener)
      if (this.listeners.size === 0) this.stop()
    }
  }

  watch(watcher: () => void) {
    this.watchers.add(watcher)
    return () => {
      this.watchers.delete(watcher)
    }
  }

  private setStatus(status: LiveStatus) {
    if (status === this.status) return
    this.status = status
    this.watchers.forEach((watcher) => watcher())
  }

  private readonly online = () => {
    if (!this.running) return
    this.clearTimer()
    this.setStatus('reconnecting')
    void this.connect()
  }

  private readonly offline = () => {
    this.setStatus('offline')
    // The stream is dead; the next attempt waits for the browser's
    // "online", which reconnects at once.
    this.controller?.abort()
    this.controller = null
    this.clearTimer()
  }

  start() {
    this.running = true
    window.addEventListener('online', this.online)
    window.addEventListener('offline', this.offline)
    void this.connect()
  }

  stop() {
    this.running = false
    window.removeEventListener('online', this.online)
    window.removeEventListener('offline', this.offline)
    this.clearTimer()
    this.controller?.abort()
    this.controller = null
    this.failures = 0
    this.status = 'connecting'
  }

  private clearTimer() {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
  }

  private async connect() {
    this.controller?.abort()
    const controller = new AbortController()
    this.controller = controller
    try {
      const response = await this.fetcher(`${API_BASE}/api/events`, {
        headers: {
          Accept: 'text/event-stream',
          ...authHeaders(),
          ...(this.lastEventId ? { 'Last-Event-ID': this.lastEventId } : {}),
        },
        signal: controller.signal,
        cache: 'no-store',
      })
      if (!response.ok || !response.body) throw new Error(`events ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parsed = parseEvents(buffer)
        buffer = parsed.rest
        this.lastContact = Date.now()
        this.failures = 0
        this.setStatus('live')
        for (const item of parsed.events) this.deliver(item)
      }
      if (this.superseded(controller)) return
      // The server ends every stream within a minute: carry straight on.
      void this.connect()
    } catch {
      if (this.superseded(controller)) return
      this.failures += 1
      this.setStatus(navigator.onLine === false ? 'offline' : 'reconnecting')
      this.clearTimer()
      this.timer = setTimeout(() => void this.connect(), backoff(this.failures))
    }
  }

  /** Stopped, or replaced by a newer connection: this one says nothing more. */
  private superseded(controller: AbortController) {
    return !this.running || this.controller !== controller
  }

  private deliver(item: ServerEvent) {
    if (item.id) this.lastEventId = item.id
    if (item.event !== 'run' && item.event !== 'connector') return
    let change: LiveChange
    try {
      change = JSON.parse(item.data) as LiveChange
    } catch {
      return
    }
    this.listeners.forEach((listener) => listener(change))
  }
}

let shared: LiveConnection | null = null

export function liveConnection(fetcher?: typeof fetch): LiveConnection {
  if (!shared) shared = new LiveConnection(fetcher)
  return shared
}

/** For tests: forget the shared connection. */
export function resetLive() {
  shared?.stop()
  shared = null
}

/** Listen for the owner's changes while the component is shown, and
 *  read the connection's state. */
export function useLive(onChange: Listener) {
  const connection = liveConnection()
  const latest = useRef(onChange)
  latest.current = onChange
  useEffect(() => connection.listen((change) => latest.current(change)), [connection])
  const status = useSyncExternalStore(
    (watcher) => connection.watch(watcher),
    () => connection.status,
  )
  return { status, lastContact: connection.lastContact }
}
