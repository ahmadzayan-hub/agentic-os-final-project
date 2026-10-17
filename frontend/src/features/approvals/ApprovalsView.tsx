import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { api, ApiError } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import type { RunDetail, RunSummary } from '../../shared/types'
import { ApprovalCard } from '../runs/ApprovalCard'
import { runStore } from '../runs/runStore'

export function ApprovalsView({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const { t, formatDate, formatNumber } = useI18n()
  const visible = useRef(true)
  useLayoutEffect(() => { visible.current = true; return () => { visible.current = false } }, [])
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [open, setOpen] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [receipt, setReceipt] = useState<string | null>(null)
  const refresh = useCallback(async () => {
    try { const result = await api.listRuns(); setRuns(result.runs); setError(null) }
    catch (err) { setError(err instanceof ApiError ? err.message : t('approvals.failed')) }
  }, [t])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    const update = () => void refresh()
    window.addEventListener('focus', update)
    return () => window.removeEventListener('focus', update)
  }, [refresh])
  const waiting = (runs ?? []).filter((run) => run.state === 'awaiting_approval').sort((a, b) => a.updated_at.localeCompare(b.updated_at))
  async function review(id: string) {
    setBusy(true); setError(null); setReceipt(null)
    try { const detail = await api.getRun(id); if (!visible.current) return; runStore.receive(detail); setOpen(detail) }
    catch (err) { setError(err instanceof ApiError ? err.message : t('approvals.failed')) }
    finally { setBusy(false) }
  }
  return <section className="panel" aria-label={t('approvals.title')}><div className="panel__inner panel__inner--wide">
    <div className="panel__header"><div><p className="eyebrow">{t('cockpit.humanDecision')}</p><h2 className="panel__title">{t('approvals.title')}</h2><p className="panel__desc">{t('approvals.desc')}</p></div><button type="button" className="btn btn--ghost" onClick={() => void refresh()}><Icon name="refresh" size={16} />{t('approvals.refresh')}</button></div>
    <p className="panel__note">{t('approvals.scope', { n: formatNumber(runs?.length ?? 0) })}</p>
    {error ? <p className="statusline statusline--error" role="alert" dir="auto">{error}</p> : null}
    {receipt ? <p className="assurance-strip" role="status">{receipt}</p> : null}
    {!runs && !error ? <div className="card" role="status" aria-label={t('approvals.loading')}><div className="skeleton skeleton--title" /><div className="skeleton skeleton--line" /></div> : null}
    {runs && !waiting.length ? <div className="card empty"><div className="empty__icon"><Icon name="shield" size={30} /></div><h3 className="empty__title">{t('approvals.empty')}</h3><p className="empty__text">{t('approvals.emptyText')}</p></div> : null}
    <div className="approval-inbox">{waiting.map((run) => <article className="card" key={run.id}>
      <div className="panel__header"><div><h3 className="card__title" dir="auto">{run.goal}</h3><p className="card__meta"><bdi>{run.dataset_name}</bdi> · {formatDate(run.updated_at)}</p></div><span className="assurance-badge assurance-badge--waiting">{t('runs.approval')}</span></div>
      <div className="dialog__actions"><button type="button" className="btn btn--ghost" onClick={() => onOpenRun(run.id)}>{t('approvals.openRun')}</button><button type="button" className="btn btn--primary" disabled={busy} onClick={() => void review(run.id)}>{t('overview.review')}</button></div>
      {open?.id === run.id ? <ApprovalCard detail={open} onDecision={(detail) => { setReceipt(detail.report?.published_path ? `${t('cockpit.published')} · ${detail.report.published_path}` : t('approvals.recorded')); setOpen(null); void refresh() }} /> : null}
    </article>)}</div>
  </div></section>
}
