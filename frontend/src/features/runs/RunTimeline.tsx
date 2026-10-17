import { useState } from 'react'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { Icon } from '../../shared/components/Icon'
import { stateLabel } from '../../shared/labels'
import type { Pipelines, RunDetail, RunTask } from '../../shared/types'
import { BANDS, groupedTasks, planRoles, roleBand } from './pipeline'

const STATES: Record<string, string> = { succeeded: '✓', failed: '✕', skipped: '—', cancelled: '—', running: '…', awaiting_approval: '!', pending: '·' }

export function PlanPreview({ pipelines, profile, joined = false }: { pipelines: Pipelines | null; profile: string; joined?: boolean }) {
  const { t, formatNumber } = useI18n()
  const roles = planRoles(pipelines, profile, joined)
  return <details className="plan-preview"><summary><Icon name="activity" size={17} /><span>{t('cockpit.planTitle')}</span><span className="plan-preview__count">{t('cockpit.stageCount', { n: formatNumber(roles.length) })}</span></summary>
    <p className="field__help">{t('cockpit.planHelp')}</p><div className="plan-preview__bands">{BANDS.map((band) => <div key={band}><h4>{t(`cockpit.band.${band}`)}</h4><ol>{roles.filter((role) => roleBand(role, pipelines) === band).map((role) => <li key={role} dir="auto">{pipelines?.stages.find((stage) => stage.role === role)?.title ?? t(`cockpit.role.${role}` as MessageKey)}</li>)}</ol></div>)}</div>
  </details>
}

export function RunTimeline({ run, pipelines, onEvidence }: {
  run: RunDetail; pipelines: Pipelines | null; onEvidence: (task: RunTask) => void
}) {
  const { t, tx, formatNumber } = useI18n()
  const [expanded, setExpanded] = useState(() => window.matchMedia('(min-width: 1100px)').matches)
  const completed = run.tasks.filter((task) => ['succeeded', 'skipped'].includes(task.state)).length
  return <aside className="card run-timeline" aria-label={t('runs.pipeline')}>
    <div className="run-timeline__head"><span className="eyebrow">{t('cockpit.orchestrated')}</span><h3 className="card__title">{t('runs.pipeline')}</h3><span className="run-timeline__count">{t('cockpit.progress', { done: formatNumber(completed), total: formatNumber(run.tasks.length) })}</span></div>
    <progress value={completed} max={Math.max(run.tasks.length, 1)} aria-label={t('runs.pipeline')} />
    <p className="controlrow__help">{tx('runs.pipelineDesc', { hermes: <strong>Hermes</strong> })}</p>
    <details className="run-timeline__disclosure" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}><summary>{t('cockpit.showPipeline')}</summary><div className="pipeline__bands">{groupedTasks(run.tasks, pipelines).map(({ band, tasks }) => <details key={band} open className="pipeline__band"><summary><span>{t(`cockpit.band.${band}`)}</span><span>{formatNumber(tasks.filter((task) => ['succeeded', 'skipped'].includes(task.state)).length)} / {formatNumber(tasks.length)}</span></summary><ul className="runtasks">
      {tasks.map((task) => <li key={task.id} className={`runtask runtask--${task.state}`}><span className="runtask__mark" aria-hidden="true">{STATES[task.state] ?? '·'}</span><div className="runtask__body"><span className="controlrow__label" dir="auto" lang={run.report_language}>{task.title}</span><span className="controlrow__help">{stateLabel(t, task.state)}</span>{task.summary ? <p className="controlrow__help" dir="auto" lang={run.report_language}>{task.summary}</p> : null}{task.claims.length || task.quality_checks.length ? <button type="button" className="evidence-link" onClick={() => onEvidence(task)}>{t('cockpit.inspectStage')}<Icon name="search" size={13} /></button> : null}</div></li>)}
    </ul></details>)}</div></details>
  </aside>
}
