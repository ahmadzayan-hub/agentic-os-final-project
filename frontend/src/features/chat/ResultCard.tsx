import { useI18n } from '../../i18n'
import { Icon } from '../../shared/components/Icon'
import { stateLabel } from '../../shared/labels'
import type { TranscriptEntry } from '../../shared/types'
import { useRun } from '../runs/runStore'

export function cardType(entry: TranscriptEntry): 'run' | 'memory' | 'preference' | null {
  if (entry.role !== 'agent') return null
  if (['start_run', 'run_status', 'explain_report', 'runtime'].includes(entry.action ?? '') && typeof entry.result?.run_id === 'string') return 'run'
  if (['remember', 'recall'].includes(entry.action ?? '')) return 'memory'
  if (entry.action === 'set_preference') return 'preference'
  return null
}

function RunCard({ id, onOpen }: { id: string; onOpen?: (id: string) => void }) {
  const { t } = useI18n()
  const snapshot = useRun(id)
  return <div className="result-card"><span className="result-card__icon"><Icon name="activity" size={20} /></span><div className="result-card__body"><p className="eyebrow">{t('cards.run')}</p><p dir="auto">{snapshot.detail?.goal ?? t('cockpit.loading')}</p><p className="card__meta">{snapshot.error ? t('cards.unavailable') : snapshot.detail ? stateLabel(t, snapshot.detail.state) : t('cards.loading')}</p></div>{onOpen ? <button className="btn btn--ghost" type="button" onClick={() => onOpen(id)}>{t('approvals.openRun')}</button> : null}</div>
}

export function ResultCard({ entry, onOpenRun }: { entry: TranscriptEntry; onOpenRun?: (id: string) => void }) {
  const { t } = useI18n()
  const kind = cardType(entry)
  if (kind === 'run') return <RunCard id={entry.result!.run_id!} onOpen={onOpenRun} />
  if (kind === 'memory' || kind === 'preference') return <p className="result-label"><Icon name={kind === 'memory' ? 'memory' : 'settings'} size={14} />{t(kind === 'memory' ? 'cards.memory' : 'cards.preference')}</p>
  return null
}

export function ToolCards({ entry }: { entry: TranscriptEntry }) {
  const { t, plural } = useI18n()
  if (!entry.steps?.length) return null
  return <details className="tool-cards"><summary>{plural('msg.toolCalls', entry.steps.length)}</summary>{entry.steps.map((step, index) => <article key={`${step.tool}-${index}`} className="tool-card"><div><code dir="ltr">{step.tool}</code><span className={step.ok ? 'tool-card__allowed' : 'tool-card__refused'}>{t(step.ok ? 'cards.allowed' : 'cards.refused')}</span></div><details><summary>{t('cards.arguments')}</summary><pre dir="ltr">{JSON.stringify(step.arguments, null, 2)}</pre></details><p dir="auto">{step.text}</p></article>)}</details>
}
