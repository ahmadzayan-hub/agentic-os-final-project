import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n'
import { api, ApiError } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import { stateLabel, typeLabel } from '../../shared/labels'
import type { RunDetail, RunSummary, Usage } from '../../shared/types'
import type { RunPreset } from '../runs/RunsView'
import { countRuns, latestWithFindings, recentRuns, RUN_PAGE, waitingForApproval } from './summary'

interface OverviewViewProps {
  onOpenRun: (id: string) => void
  onStart: (preset: RunPreset | null) => void
  onApprovals?: () => void
}

/** Where the workspace stands, on one screen: the figures, the latest
 *  findings, what is waiting at the approval gate, and the newest runs.
 *  Everything comes from existing endpoints; nothing is computed here
 *  that the server did not already say. */
export function OverviewView({ onOpenRun, onStart, onApprovals }: OverviewViewProps) {
  const { t, tx, formatNumber, formatDate } = useI18n()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [usageFailed, setUsageFailed] = useState(false)
  const [latest, setLatest] = useState<RunDetail | null>(null)
  const [latestFailed, setLatestFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setFailed(null)
    setRuns(null)
    setLatest(null)
    setLatestFailed(false)
    setUsageFailed(false)
    api
      .listRuns()
      .then(async (result) => {
        if (cancelled) return
        setRuns(result.runs)
        const source = latestWithFindings(result.runs)
        if (!source) return
        try {
          const detail = await api.getRun(source.id)
          if (!cancelled) setLatest(detail)
        } catch {
          if (!cancelled) setLatestFailed(true)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setFailed(error instanceof ApiError ? error.message : t('overview.failed'))
        }
      })
    api
      .usage()
      .then((result) => !cancelled && setUsage(result))
      .catch(() => !cancelled && setUsageFailed(true))
    return () => {
      cancelled = true
    }
    // `t` changes only with the locale; a retry is the key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])

  const header = (
    <div className="panel__header">
      <div>
        <h2 className="panel__title">{t('overview.title')}</h2>
        <p className="panel__desc">{t('overview.desc')}</p>
      </div>
      <button type="button" className="btn btn--primary" onClick={() => onStart(null)}>
        <Icon name="plus" size={16} />
        {t('overview.start')}
      </button>
    </div>
  )

  if (failed) {
    return (
      <section className="panel" aria-label={t('overview.aria')}>
        <div className="panel__inner panel__inner--wide">
          {header}
          <div className="card">
            <p className="statusline statusline--error" role="alert" dir="auto">
              {failed}
            </p>
            <button type="button" className="btn btn--ghost" onClick={() => setAttempt((n) => n + 1)}>
              <Icon name="refresh" size={16} />
              {t('common.tryAgain')}
            </button>
          </div>
        </div>
      </section>
    )
  }

  if (!runs) {
    return (
      <section className="panel" aria-label={t('overview.aria')}>
        <div className="panel__inner panel__inner--wide">
          {header}
          <div className="kpis" role="status" aria-label={t('overview.loading')}>
            {[0, 1, 2, 3].map((n) => (
              <div key={n} className="kpi">
                <div className="skeleton skeleton--line" />
                <div className="skeleton skeleton--title" />
              </div>
            ))}
          </div>
        </div>
      </section>
    )
  }

  if (runs.length === 0) {
    return (
      <section className="panel" aria-label={t('overview.aria')}>
        <div className="panel__inner panel__inner--wide">
          {header}
          <div className="card empty">
            <div className="empty__icon">
              <Icon name="dashboard" size={32} />
            </div>
            <h3 className="empty__title">{t('overview.emptyTitle')}</h3>
            <p className="empty__text">{t('overview.emptyText')}</p>
            <div className="empty__actions">
              <button type="button" className="btn btn--primary" onClick={() => onStart(null)}>
                {t('overview.trySample')}
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => onStart({ kind: 'upload' })}
              >
                {t('overview.addDataset')}
              </button>
            </div>
          </div>
        </div>
      </section>
    )
  }

  const counts = countRuns(runs)
  const waiting = waitingForApproval(runs)
  const recent = recentRuns(runs)
  const findings = latest ? latest.reports.filter((report) => (report.headline ?? '').trim()) : []
  const reportLang = latest?.report_language === 'ar' ? 'ar' : 'en'

  const tiles = [
    {
      key: 'finished',
      label: t('overview.finished'),
      value: formatNumber(counts.finished),
      sub: counts.active > 0 ? t('overview.inProgress', { n: formatNumber(counts.active) }) : '',
      attention: false,
    },
    {
      key: 'waiting',
      label: t('overview.waitingTile'),
      value: formatNumber(counts.waiting),
      sub: '',
      attention: counts.waiting > 0,
    },
    {
      key: 'datasets',
      label: t('usage.datasets'),
      value: usage ? formatNumber(usage.datasets.used) : '—',
      sub: usage
        ? t('overview.ofLimit', { limit: formatNumber(usage.datasets.limit) })
        : usageFailed
          ? t('usage.unavailable')
          : '',
      attention: false,
    },
    {
      key: 'today',
      label: t('usage.runs'),
      value: usage ? formatNumber(usage.runs_today.used) : '—',
      sub: usage
        ? t('overview.ofLimit', { limit: formatNumber(usage.runs_today.limit) })
        : usageFailed
          ? t('usage.unavailable')
          : '',
      attention: false,
    },
  ]

  return (
    <section className="panel" aria-label={t('overview.aria')}>
      <div className="panel__inner panel__inner--wide">
        {header}

        <dl className="kpis">
          {tiles.map((tile) => (
            <div key={tile.key} className={`kpi ${tile.attention ? 'kpi--attention' : ''}`}>
              <dt className="kpi__label">{tile.label}</dt>
              <dd className="kpi__value">{tile.value}</dd>
              {tile.sub ? <dd className="kpi__sub">{tile.sub}</dd> : null}
            </div>
          ))}
        </dl>
        {counts.capped ? (
          <p className="panel__note">{t('overview.capped', { n: formatNumber(RUN_PAGE) })}</p>
        ) : null}

        <div className="overview__grid">
          <div className="card">
            <h3 className="card__title">{t('overview.findings')}</h3>
            {latest ? (
              <>
                <p className="card__meta">
                  {tx('overview.findingsFrom', {
                    goal: <span dir="auto">{latest.goal}</span>,
                    state: <strong>{stateLabel(t, latest.state)}</strong>,
                  })}
                </p>
                {findings.length > 0 ? (
                  <ul className="findings">
                    {findings.map((report) => (
                      <li key={report.type} className="finding">
                        <span className="finding__type">
                          {typeLabel(t, report.type, report.title)}
                        </span>
                        <span
                          className="finding__text"
                          lang={reportLang}
                          dir={reportLang === 'ar' ? 'rtl' : 'ltr'}
                        >
                          {report.headline}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="card__empty">{t('overview.findingsNone')}</p>
                )}
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => onOpenRun(latest.id)}
                >
                  {t('overview.openAnalysis')}
                </button>
              </>
            ) : latestFailed ? (
              <p className="card__empty">{t('overview.findingsFailed')}</p>
            ) : counts.finished + counts.waiting === 0 ? (
              <p className="card__empty">{t('overview.findingsNone')}</p>
            ) : (
              <>
                <div className="skeleton skeleton--line" />
                <div className="skeleton skeleton--line skeleton--short" />
              </>
            )}
          </div>

          <div className="card">
            <h3 className="card__title">{t('overview.waiting')}</h3>
            {onApprovals ? <button type="button" className="evidence-link" onClick={onApprovals}>{t('approvals.openInbox')}</button> : null}
            {waiting.length === 0 ? (
              <p className="card__empty">{t('overview.waitingNone')}</p>
            ) : (
              <ul className="controls__list">
                {waiting.map((run) => (
                  <li key={run.id}>
                    <button type="button" className="controlrow" onClick={() => onOpenRun(run.id)}>
                      <Icon name="shield" size={17} />
                      <span className="controlrow__body">
                        <span className="controlrow__label" dir="auto">
                          {run.goal}
                        </span>
                        <span className="controlrow__help">
                          <span dir="auto">{run.dataset_name}</span> ·{' '}
                          {t('overview.waitingSince', { date: formatDate(run.updated_at) })}
                        </span>
                      </span>
                      <span className="controlrow__action">{t('overview.review')}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="card">
          <h3 className="card__title">{t('overview.recent')}</h3>
          <ul className="controls__list">
            {recent.map((run) => (
              <li key={run.id}>
                <button type="button" className="controlrow" onClick={() => onOpenRun(run.id)}>
                  <Icon name="clock" size={17} />
                  <span className="controlrow__body">
                    <span className="controlrow__label" dir="auto">
                      {run.goal}
                    </span>
                    <span className="controlrow__help">
                      <span dir="auto">{run.dataset_name}</span> · {stateLabel(t, run.state)} ·{' '}
                      {formatDate(run.updated_at)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="btn btn--subtle" onClick={() => onStart(null)}>
            {t('overview.seeAll')}
          </button>
        </div>
      </div>
    </section>
  )
}

