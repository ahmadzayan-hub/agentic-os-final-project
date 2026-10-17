import { useEffect, useSyncExternalStore } from 'react'
import { api, ApiError } from '../../shared/api'
import type { RunDetail } from '../../shared/types'
import { appendEvents, snapshotEvents } from './runEvents'
import type { RunEvent } from './runEvents'

export interface RunSnapshot {
  detail: RunDetail | null
  events: RunEvent[]
  loading: boolean
  pending: boolean
  error: Error | null
  interrupted: boolean
  receivedAt: string | null
}

const EMPTY: RunSnapshot = {
  detail: null, events: [], loading: false, pending: false,
  error: null, interrupted: false, receivedAt: null,
}

export function reduceSnapshot(state: RunSnapshot, detail: RunDetail): RunSnapshot {
  return {
    ...state, detail,
    events: appendEvents(state.events, snapshotEvents(state.detail, detail)),
    loading: false, error: null, interrupted: false,
    receivedAt: new Date().toISOString(),
  }
}

type Gateway = Pick<typeof api, 'getRun' | 'advanceRun'>
interface Entry {
  state: RunSnapshot
  listeners: Set<() => void>
  observers: number
  drivers: number
  timer: ReturnType<typeof setTimeout> | null
  request: Promise<void> | null
}

/** One scheduler per run. Reading a chat card never advances an analysis. */
export function createRunStore(gateway: Gateway = api) {
  const entries = new Map<string, Entry>()
  let epoch = 0
  function entry(id: string): Entry {
    if (!entries.has(id)) entries.set(id, {
      state: EMPTY, listeners: new Set(), observers: 0, drivers: 0, timer: null, request: null,
    })
    return entries.get(id)!
  }
  function change(item: Entry, state: RunSnapshot) {
    item.state = state
    item.listeners.forEach((listener) => listener())
  }
  function stop(item: Entry) {
    if (item.timer) clearTimeout(item.timer)
    item.timer = null
  }
  function schedule(id: string, delay?: number) {
    const item = entry(id)
    stop(item)
    if (!item.observers || item.state.pending || item.request || item.state.interrupted) return
    const detail = item.state.detail
    const active = detail && ['queued', 'running'].includes(detail.state) && !detail.paused
    if (detail && !active && detail.state !== 'awaiting_approval' && !detail.paused) return
    item.timer = setTimeout(() => void refresh(id, Boolean(active && item.drivers)), delay ?? (active && item.drivers ? 350 : 2500))
  }
  async function refresh(id: string, advance = false): Promise<void> {
    const item = entry(id)
    if (item.request || item.state.pending) return item.request ?? undefined
    const generation = epoch
    const operation = async () => {
      try {
        const detail = await (advance ? gateway.advanceRun(id) : gateway.getRun(id))
        if (generation !== epoch) return
        change(item, reduceSnapshot(item.state, detail))
      } catch (error) {
        if (generation !== epoch) return
        const throttled = error instanceof ApiError && error.status === 429
        change(item, { ...item.state, loading: false, error: error instanceof Error ? error : new Error(String(error)), interrupted: !throttled })
      } finally {
        if (generation === epoch) {
          item.request = null
          schedule(id, item.state.error instanceof ApiError && item.state.error.status === 429 ? 1500 : undefined)
        }
      }
    }
    item.request = operation()
    return item.request
  }
  return {
    get(id: string | null): RunSnapshot { return id ? entry(id).state : EMPTY },
    subscribe(id: string | null, listener: () => void) {
      if (!id) return () => {}
      const item = entry(id)
      item.listeners.add(listener)
      return () => { item.listeners.delete(listener) }
    },
    watch(id: string, advance = false) {
      const item = entry(id)
      item.observers += 1
      if (advance) item.drivers += 1
      if (!item.state.detail) change(item, { ...item.state, loading: true })
      void refresh(id)
      return () => {
        item.observers = Math.max(0, item.observers - 1)
        if (advance) item.drivers = Math.max(0, item.drivers - 1)
        if (!item.observers) stop(item)
        else schedule(id)
      }
    },
    receive(detail: RunDetail) {
      const item = entry(detail.id)
      change(item, reduceSnapshot(item.state, detail))
      schedule(detail.id)
    },
    async retry(id: string) {
      const item = entry(id)
      change(item, { ...item.state, error: null, interrupted: false })
      await refresh(id)
    },
    async mutate(id: string, operation: () => Promise<RunDetail>): Promise<RunDetail | null> {
      const item = entry(id)
      if (item.state.pending) return null
      stop(item)
      const generation = epoch
      change(item, { ...item.state, pending: true, error: null })
      try {
        await item.request
        if (generation !== epoch) return null
        const detail = await operation()
        if (generation !== epoch) return null
        change(item, reduceSnapshot(item.state, detail))
        return detail
      } catch (error) {
        if (generation === epoch) {
          // A failed POST is never replayed. Reconcile using a read, then
          // keep the refusal visible beside the original report.
          try {
            const detail = await gateway.getRun(id)
            if (generation === epoch) change(item, reduceSnapshot(item.state, detail))
          } catch { /* retain last snapshot */ }
          if (generation === epoch) change(item, { ...item.state, error: error instanceof Error ? error : new Error(String(error)), interrupted: true })
        }
        throw error
      } finally {
        if (generation === epoch) {
          change(item, { ...item.state, pending: false })
          schedule(id)
        }
      }
    },
    reset() {
      epoch += 1
      entries.forEach((item) => { stop(item); change(item, EMPTY) })
      entries.clear()
    },
  }
}

export const runStore = createRunStore()

export function useRun(id: string | null, advance = false) {
  const state = useSyncExternalStore(
    (listener) => runStore.subscribe(id, listener),
    () => runStore.get(id),
    () => EMPTY,
  )
  useEffect(() => id ? runStore.watch(id, advance) : undefined, [id, advance])
  return state
}
