import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  applyLocale,
  currentLocale,
  localeFromPreference,
  preferenceFor,
  storedLocale,
  translate,
  translatePlural,
} from '../i18n'
import type { Locale, MessageKey, Vars } from '../i18n'
import { api, ApiError, hasToken, storeToken } from '../shared/api'
import type {
  ActivityEvent,
  ActivityKind,
  AuthConfig,
  ConnectionStatus,
  IdentityInfo,
  SessionState,
} from '../shared/types'

export interface OperationOutcome {
  ok: boolean
  message: string
}

interface Store {
  authConfig: AuthConfig | null
  needsSignIn: boolean
  identity: IdentityInfo | null
  signIn: (token: string) => Promise<void>
  signOut: () => void
  session: SessionState | null
  bootError: string | null
  status: ConnectionStatus
  sending: boolean
  failedText: string | null
  events: ActivityEvent[]
  lastSyncedAt: string | null
  /** A run the assistant just started from the chat; the shell opens it. */
  openRun: { id: string; nonce: number } | null
  start: () => Promise<void>
  send: (text: string) => Promise<void>
  retryFailed: () => Promise<void>
  dismissFailed: () => void
  clearHistory: () => Promise<OperationOutcome>
  setPreference: (key: string, value: string) => Promise<OperationOutcome>
  /** Interface language and the agent's reply language, changed together. */
  setLanguage: (locale: Locale) => Promise<OperationOutcome>
  addMemory: (information: string, category?: string) => Promise<OperationOutcome>
  updateMemory: (key: string, information: string, category?: string) => Promise<OperationOutcome>
  deleteMemory: (key: string) => Promise<OperationOutcome>
  clearMemory: () => Promise<OperationOutcome>
  exportData: () => Promise<OperationOutcome>
  endSession: () => Promise<OperationOutcome>
}

const StoreContext = createContext<Store | null>(null)

const SESSION_KEY = 'aos-session'

function readStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function storeSessionId(id: string) {
  try {
    localStorage.setItem(SESSION_KEY, id)
  } catch {
    /* private mode — the session simply won't survive a refresh */
  }
}

export function useStore(): Store {
  const store = useContext(StoreContext)
  if (!store) throw new Error('useStore must be used inside <StoreProvider>')
  return store
}

let eventId = 0

export function StoreProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [sending, setSending] = useState(false)
  const [failedText, setFailedText] = useState<string | null>(null)
  const [offline, setOffline] = useState(!navigator.onLine)
  const [lastError, setLastError] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null)
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null)
  const [identity, setIdentity] = useState<IdentityInfo | null>(null)
  const [needsSignIn, setNeedsSignIn] = useState(false)
  const pendingCount = useRef(0)
  const [pending, setPending] = useState(0)
  const [openRun, setOpenRun] = useState<{ id: string; nonce: number } | null>(null)

  const pushEvent = useCallback(
    (code: MessageKey, kind: ActivityKind, detail?: string, vars?: Vars) => {
      eventId += 1
      const event: ActivityEvent = {
        id: eventId,
        code,
        vars,
        kind,
        detail,
        time: new Date().toISOString(),
      }
      setEvents((current) => [event, ...current].slice(0, 100))
    },
    [],
  )

  const beginWork = useCallback(() => {
    pendingCount.current += 1
    setPending(pendingCount.current)
  }, [])

  const endWork = useCallback(() => {
    pendingCount.current = Math.max(0, pendingCount.current - 1)
    setPending(pendingCount.current)
  }, [])

  useEffect(() => {
    function goOnline() {
      setOffline(false)
      pushEvent('event.connection.restored', 'success')
    }
    function goOffline() {
      setOffline(true)
      pushEvent('event.connection.lost', 'error')
    }
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [pushEvent])

  // A 401 anywhere means the token is missing, expired, or revoked:
  // drop it and return the user to the sign-in screen.
  const handleUnauthorized = useCallback(() => {
    storeToken(null)
    setIdentity(null)
    setSession(null)
    setNeedsSignIn(true)
  }, [])

  const start = useCallback(async () => {
    beginWork()
    setBootError(null)
    try {
      // The agent phrases its own replies from the session's language
      // preference; seeding it from the interface language means the
      // welcome message is already in the right language.
      const state = await api.createSession(preferenceFor(currentLocale()))
      setSession(state)
      storeSessionId(state.session_id)
      setFailedText(null)
      setLastError(false)
      setOffline(false)
      setLastSyncedAt(new Date().toISOString())
      pushEvent('event.session.started', 'success', state.agent_name)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleUnauthorized()
        return
      }
      const message = error instanceof ApiError ? error.message : translate('outcome.startFailed')
      setBootError(message)
      pushEvent('event.session.startFailed', 'error', message)
    } finally {
      endWork()
    }
  }, [beginWork, endWork, pushEvent, handleUnauthorized])

  /** A restored session may have been created in another language, or
   *  on another device. The browser's explicit choice wins and the agent
   *  is told; with no explicit choice, the session's language is applied
   *  to the interface without being recorded as a choice. */
  const reconcileLanguage = useCallback((state: SessionState) => {
    const chosen = storedLocale()
    const sessionLocale = localeFromPreference(state.preferences.language)
    if (chosen === null) {
      if (sessionLocale !== currentLocale()) applyLocale(sessionLocale, false)
      return
    }
    if (chosen !== sessionLocale && !state.ended) {
      api
        .setPreference(state.session_id, 'language', preferenceFor(chosen))
        .then((result) => setSession(result.state))
        .catch(() => {
          /* the next preference change carries the language with it */
        })
    }
  }, [])

  // On page load, restore the previous session when the server still has
  // it and it hasn't ended; otherwise fall back to a fresh session.
  const bootstrap = useCallback(async () => {
    // Ask the server whether this deployment requires an account before
    // touching any protected endpoint.
    try {
      const config = await api.authConfig()
      setAuthConfig(config)
      if (config.mode === 'jwt') {
        if (!hasToken()) {
          setNeedsSignIn(true)
          return
        }
        try {
          setIdentity(await api.identity())
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            handleUnauthorized()
            return
          }
        }
      }
    } catch {
      // An unreachable config endpoint is handled by the session boot
      // below, which surfaces a retryable error state.
    }

    const storedId = readStoredSessionId()
    if (storedId) {
      beginWork()
      try {
        const state = await api.getSession(storedId)
        if (!state.ended) {
          setSession(state)
          setOffline(false)
          setLastSyncedAt(new Date().toISOString())
          pushEvent(
            'event.session.restored',
            'success',
            translatePlural('session.restoredMessages', state.transcript.length),
          )
          reconcileLanguage(state)
          return
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          handleUnauthorized()
          return
        }
        // Offline or server error: surface it instead of silently
        // replacing the session. A 404 just means the session expired.
        if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
          setBootError(error.message)
          pushEvent('event.session.restoreFailed', 'error', error.message)
          return
        }
      } finally {
        endWork()
      }
    }
    await start()
  }, [beginWork, endWork, pushEvent, start, handleUnauthorized, reconcileLanguage])

  const signIn = useCallback(
    async (token: string) => {
      storeToken(token)
      setNeedsSignIn(false)
      setBootError(null)
      try {
        setIdentity(await api.identity())
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          handleUnauthorized()
          return
        }
      }
      await start()
    },
    [handleUnauthorized, start],
  )

  const signOut = useCallback(() => {
    try {
      localStorage.removeItem('aos-session')
    } catch {
      /* nothing stored */
    }
    handleUnauthorized()
    pushEvent('event.signedOut', 'info')
  }, [handleUnauthorized, pushEvent])

  const startedOnce = useRef(false)
  useEffect(() => {
    // Guard against React StrictMode double-invoking the mount effect in
    // development, which would otherwise open two sessions.
    if (startedOnce.current) return
    startedOnce.current = true
    void bootstrap()
    // bootstrap() is stable; run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const send = useCallback(
    async (text: string) => {
      if (!session || sending) return
      setSending(true)
      setFailedText(null)
      beginWork()
      try {
        const result = await api.sendMessage(session.session_id, text)
        setSession(result.state)
        setLastError(false)
        // Any confirmed server response proves connectivity — never stay
        // stuck in offline mode after a successful request.
        setOffline(false)
        setLastSyncedAt(new Date().toISOString())
        pushEvent(
          'event.request.completed',
          'info',
          text.length > 60 ? `${text.slice(0, 60)}…` : text,
        )
        if (result.state.ended) pushEvent('event.session.ended', 'info')
        const runId = result.reply.result?.run_id
        const startedRun = result.reply.action === 'start_run' || result.reply.action === 'runtime'
        if (startedRun && typeof runId === 'string') {
          setOpenRun({ id: runId, nonce: Date.now() })
        }
      } catch (error) {
        const message = error instanceof ApiError ? error.message : translate('outcome.requestFailed')
        setFailedText(text)
        setLastError(true)
        if (error instanceof ApiError && error.offline) setOffline(true)
        pushEvent('event.request.failed', 'error', message)
      } finally {
        setSending(false)
        endWork()
      }
    },
    [session, sending, beginWork, endWork, pushEvent],
  )

  const retryFailed = useCallback(async () => {
    const text = failedText
    if (!text) return
    setFailedText(null)
    await send(text)
  }, [failedText, send])

  const dismissFailed = useCallback(() => setFailedText(null), [])

  const runOperation = useCallback(
    async (
      operation: (sessionId: string) => Promise<{ reply_text: string; state: SessionState }>,
      code: MessageKey,
    ): Promise<OperationOutcome> => {
      if (!session) return { ok: false, message: translate('outcome.noSession') }
      beginWork()
      try {
        const result = await operation(session.session_id)
        setSession(result.state)
        setLastError(false)
        setOffline(false)
        setLastSyncedAt(new Date().toISOString())
        pushEvent(code, 'success', result.reply_text)
        return { ok: true, message: result.reply_text }
      } catch (error) {
        const message = error instanceof ApiError ? error.message : translate('outcome.requestFailed')
        if (error instanceof ApiError && error.offline) setOffline(true)
        setLastError(true)
        pushEvent(`${code}.failed` as MessageKey, 'error', message)
        return { ok: false, message }
      } finally {
        endWork()
      }
    },
    [session, beginWork, endWork, pushEvent],
  )

  const clearHistory = useCallback(
    () => runOperation((id) => api.clearHistory(id), 'event.history.cleared'),
    [runOperation],
  )
  const setPreference = useCallback(
    (key: string, value: string) =>
      runOperation((id) => api.setPreference(id, key, value), 'event.preference.changed'),
    [runOperation],
  )
  const setLanguage = useCallback(
    async (locale: Locale): Promise<OperationOutcome> => {
      // The interface switches at once; the agent is told so its next
      // reply matches. With no live session there is nothing to tell.
      applyLocale(locale)
      if (!session || session.ended) return { ok: true, message: '' }
      return runOperation(
        (id) => api.setPreference(id, 'language', preferenceFor(locale)),
        'event.preference.changed',
      )
    },
    [session, runOperation],
  )
  const addMemory = useCallback(
    (information: string, category?: string) =>
      runOperation((id) => api.addMemory(id, information, category), 'event.memory.saved'),
    [runOperation],
  )
  const updateMemory = useCallback(
    (key: string, information: string, category?: string) =>
      runOperation(
        (id) => api.updateMemory(id, key, information, category),
        'event.memory.updated',
      ),
    [runOperation],
  )
  const deleteMemory = useCallback(
    (key: string) => runOperation((id) => api.deleteMemory(id, key), 'event.memory.removed'),
    [runOperation],
  )
  const clearMemory = useCallback(
    () => runOperation((id) => api.clearMemory(id), 'event.memory.cleared'),
    [runOperation],
  )

  const exportData = useCallback(async (): Promise<OperationOutcome> => {
    if (!session) return { ok: false, message: translate('outcome.noSession') }
    beginWork()
    try {
      const payload = await api.exportData(session.session_id)
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'agentic-os-export.json'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setLastSyncedAt(new Date().toISOString())
      pushEvent('event.export.done', 'success', 'agentic-os-export.json')
      return { ok: true, message: translate('outcome.exported') }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : translate('outcome.exportFailed')
      pushEvent('event.export.failed', 'error', message)
      return { ok: false, message }
    } finally {
      endWork()
    }
  }, [session, beginWork, endWork, pushEvent])

  const endSession = useCallback(async (): Promise<OperationOutcome> => {
    if (!session) return { ok: false, message: translate('outcome.noSession') }
    beginWork()
    try {
      const state = await api.endSession(session.session_id)
      setSession(state)
      pushEvent('event.session.ended', 'info')
      return { ok: true, message: translate('outcome.sessionEnded') }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : translate('outcome.requestFailed')
      pushEvent('event.session.endFailed', 'error', message)
      return { ok: false, message }
    } finally {
      endWork()
    }
  }, [session, beginWork, endWork, pushEvent])

  const status: ConnectionStatus = offline
    ? 'offline'
    : session?.ended
      ? 'ended'
      : pending > 0
        ? 'working'
        : lastError
          ? 'error'
          : 'ready'

  const value = useMemo<Store>(
    () => ({
      authConfig,
      needsSignIn,
      identity,
      signIn,
      signOut,
      session,
      bootError,
      status,
      sending,
      failedText,
      events,
      lastSyncedAt,
      openRun,
      start,
      send,
      retryFailed,
      dismissFailed,
      clearHistory,
      setPreference,
      setLanguage,
      addMemory,
      updateMemory,
      deleteMemory,
      clearMemory,
      exportData,
      endSession,
    }),
    [
      authConfig,
      needsSignIn,
      identity,
      signIn,
      signOut,
      session,
      bootError,
      status,
      sending,
      failedText,
      events,
      lastSyncedAt,
      openRun,
      start,
      send,
      retryFailed,
      dismissFailed,
      clearHistory,
      setPreference,
      setLanguage,
      addMemory,
      updateMemory,
      deleteMemory,
      clearMemory,
      exportData,
      endSession,
    ],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}
