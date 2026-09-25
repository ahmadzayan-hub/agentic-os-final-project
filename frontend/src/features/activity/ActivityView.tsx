import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { api } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import type { IconName } from '../../shared/components/Icon'
import type { ActivityEvent, ConnectionStatus, SessionState, Usage } from '../../shared/types'

/** A limit the server enforces but the interface never shows is a trap:
 *  the first a user hears of it is a refusal. */
function UsageCard() {
  const { t, formatNumber } = useI18n()
  const [usage, setUsage] = useState<Usage | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .usage()
      .then((result) => !cancelled && setUsage(result))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [])

  // Byte units stay Latin in both languages: they are symbols, not words.
  function formatBytes(bytes: number): string {
    if (bytes < 1000) return `${formatNumber(bytes)} B`
    if (bytes < 1_000_000) return `${formatNumber(bytes / 1000, { maximumFractionDigits: 1 })} kB`
    return `${formatNumber(bytes / 1_000_000, { maximumFractionDigits: 1 })} MB`
  }

  if (failed) {
    return (
      <div className="card">
        <h3 className="card__title">{t('usage.title')}</h3>
        <p className="controlrow__help">{t('usage.unavailable')}</p>
      </div>
    )
  }
  if (!usage) {
    return (
      <div className="card">
        <h3 className="card__title">{t('usage.title')}</h3>
        <div className="skeleton skeleton--line" />
        <div className="skeleton skeleton--line" />
      </div>
    )
  }

  const rows = [
    {
      key: 'runs',
      label: t('usage.runs'),
      used: t('usage.of', {
        used: formatNumber(usage.runs_today.used),
        limit: formatNumber(usage.runs_today.limit),
      }),
      share: usage.runs_today.limit ? usage.runs_today.used / usage.runs_today.limit : 0,
      help: t('usage.resets', { n: formatNumber(usage.runs_today.remaining) }),
    },
    {
      key: 'datasets',
      label: t('usage.datasets'),
      used: t('usage.of', {
        used: formatNumber(usage.datasets.used),
        limit: formatNumber(usage.datasets.limit),
      }),
      share: usage.datasets.limit ? usage.datasets.used / usage.datasets.limit : 0,
      help: t('usage.rerun'),
    },
    {
      key: 'bytes',
      label: t('usage.storage'),
      used: t('usage.of', {
        used: formatBytes(usage.dataset_bytes.used),
        limit: formatBytes(usage.dataset_bytes.limit),
      }),
      share: usage.dataset_bytes.limit ? usage.dataset_bytes.used / usage.dataset_bytes.limit : 0,
      help: t('usage.dedupe'),
    },
  ]

  return (
    <div className="card">
      <h3 className="card__title">{t('usage.title')}</h3>
      <ul className="usage">
        {rows.map((row) => (
          <li key={row.key} className="usage__row">
            <div className="usage__head">
              <span className="controlrow__label">{row.label}</span>
              <span className="usage__value">{row.used}</span>
            </div>
            <div
              className="usage__track"
              role="meter"
              aria-valuenow={Math.round(row.share * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${row.label}: ${row.used}`}
            >
              <div
                className={`usage__fill ${row.share >= 0.9 ? 'usage__fill--high' : ''}`}
                style={{ width: `${Math.min(100, Math.round(row.share * 100))}%` }}
              />
            </div>
            <span className="controlrow__help">{row.help}</span>
          </li>
        ))}
      </ul>
      <p className="privacy-note" dir="auto">
        {t('usage.notMeasured', { list: usage.not_tracked.join(', ') })}
      </p>
    </div>
  )
}

type ActivityFilter = 'all' | 'system' | 'memory' | 'preferences' | 'errors'

const FILTERS: Array<{ id: ActivityFilter; label: MessageKey }> = [
  { id: 'all', label: 'filter.all' },
  { id: 'system', label: 'filter.system' },
  { id: 'memory', label: 'filter.memory' },
  { id: 'preferences', label: 'filter.preferences' },
  { id: 'errors', label: 'filter.errors' },
]

/** Events are classified by their code, which is stable across
 *  languages — a label regex would have to be written twice. */
function filterOf(event: ActivityEvent): ActivityFilter {
  if (event.kind === 'error') return 'errors'
  if (event.code.startsWith('event.memory.') || event.code.startsWith('event.export.')) return 'memory'
  if (event.code.startsWith('event.preference.')) return 'preferences'
  return 'system'
}

const EVENT_ICONS: Array<{ prefix: string; icon: IconName }> = [
  { prefix: 'event.session.', icon: 'power' },
  { prefix: 'event.signedOut', icon: 'power' },
  { prefix: 'event.preference.', icon: 'settings' },
  { prefix: 'event.memory.', icon: 'memory' },
  { prefix: 'event.export.', icon: 'memory' },
  { prefix: 'event.history.', icon: 'clock' },
  { prefix: 'event.connection.', icon: 'refresh' },
]

function iconFor(code: string): IconName {
  return EVENT_ICONS.find((entry) => code.startsWith(entry.prefix))?.icon ?? 'activity'
}

interface ActivityViewProps {
  events: ActivityEvent[]
  session: SessionState
  status: ConnectionStatus
  lastSyncedAt: string | null
}

/** Operational transparency: real events and real health facts only —
 *  no fabricated telemetry, no hidden reasoning. */
export function ActivityView({ events, session, status, lastSyncedAt }: ActivityViewProps) {
  const { t, plural, formatTime } = useI18n()
  const [filter, setFilter] = useState<ActivityFilter>('all')
  const online = status !== 'offline'
  const healthy = online && status !== 'error'
  const visible = filter === 'all' ? events : events.filter((event) => filterOf(event) === filter)
  const memoryCount = Object.keys(session.memory).length

  return (
    <section className="panel" aria-label={t('activity.aria')}>
      <div className="panel__inner panel__inner--split">
        <div className="panel__column">
          <div className="panel__header">
            <div>
              <h2 className="panel__title">{t('activity.title')}</h2>
              <p className="panel__desc">{t('activity.desc')}</p>
            </div>
          </div>

          {events.length > 0 ? (
            <div className="chips" role="group" aria-label={t('activity.filter')}>
              {FILTERS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className="chip"
                  aria-pressed={filter === option.id}
                  onClick={() => setFilter(option.id)}
                >
                  {t(option.label)}
                </button>
              ))}
            </div>
          ) : null}

          {events.length === 0 ? (
            <div className="card">
              <div className="empty">
                <div className="empty__icon">
                  <Icon name="activity" size={32} />
                </div>
                <p>{t('activity.none')}</p>
              </div>
            </div>
          ) : visible.length === 0 ? (
            <div className="card">
              <p className="empty">
                {t('activity.noneFiltered', {
                  filter: t(FILTERS.find((option) => option.id === filter)?.label ?? 'filter.all'),
                })}
              </p>
            </div>
          ) : (
            <div className="card">
              <ol className="timeline">
                {visible.map((event) => (
                  <li key={event.id} className="timeline__item">
                    <span className={`timeline__icon timeline__icon--${event.kind}`} aria-hidden="true">
                      <Icon name={iconFor(event.code)} size={16} />
                    </span>
                    <div className="timeline__body">
                      <p className="activity__label">{t(event.code, event.vars)}</p>
                      {event.detail ? (
                        <p className="activity__detail" dir="auto">
                          {event.detail}
                        </p>
                      ) : null}
                    </div>
                    <time className="activity__time" dateTime={event.time}>
                      {formatTime(event.time, true)}
                    </time>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>

        <div className="panel__column panel__column--side">
          <div className="card">
            <h3 className="card__title">{t('activity.health')}</h3>
            <ul className="health">
              <li className="health__row">
                <span
                  className={`health__dot ${healthy ? 'health__dot--ok' : 'health__dot--bad'}`}
                  aria-hidden="true"
                />
                <span>
                  <span className="controlrow__label">
                    {online ? t('activity.online') : t('activity.offline')}
                  </span>
                  <span className="controlrow__help">
                    {healthy
                      ? t('activity.connected')
                      : online
                        ? t('activity.lastFailed')
                        : t('activity.willFail')}
                  </span>
                </span>
              </li>
              <li className="health__row">
                <span
                  className={`health__dot ${session.memory_persisted ? 'health__dot--ok' : 'health__dot--warn'}`}
                  aria-hidden="true"
                />
                <span>
                  <span className="controlrow__label">
                    {session.memory_persisted
                      ? t('activity.storageActive')
                      : t('activity.notPersisted')}
                  </span>
                  <span className="controlrow__help">
                    {session.memory_persisted ? t('activity.savedTo') : t('activity.noFile')}
                  </span>
                </span>
              </li>
              <li className="health__row">
                <span className="health__dot health__dot--ok" aria-hidden="true" />
                <span>
                  <span className="controlrow__label">{plural('activity.entries', memoryCount)}</span>
                  <span className="controlrow__help">
                    {plural('activity.messages', session.transcript.length)}
                  </span>
                </span>
              </li>
              <li className="health__row">
                <span
                  className={`health__dot ${lastSyncedAt ? 'health__dot--ok' : 'health__dot--warn'}`}
                  aria-hidden="true"
                />
                <span>
                  <span className="controlrow__label">
                    {lastSyncedAt
                      ? t('activity.lastResponse', { time: formatTime(lastSyncedAt, true) })
                      : t('activity.noResponses')}
                  </span>
                  <span className="controlrow__help">{t('activity.lastHelp')}</span>
                </span>
              </li>
            </ul>
          </div>

          <UsageCard />
        </div>
      </div>
    </section>
  )
}
