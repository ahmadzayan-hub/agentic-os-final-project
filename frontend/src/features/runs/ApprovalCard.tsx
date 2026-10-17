import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, ApiError } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import type { RunDetail } from '../../shared/types'
import { runStore, useRun } from './runStore'

export function ApprovalCard({ detail, onDecision }: {
  detail: RunDetail
  onDecision?: (detail: RunDetail) => void
}) {
  const { t, formatNumber } = useI18n()
  const snapshot = useRun(detail.id)
  const run = snapshot.detail ?? detail
  const approval = run.approvals.find((item) => item.state === 'pending')
  const [message, setMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  if (!approval) return null
  const busy = submitting || snapshot.pending

  async function decide(decision: 'approve' | 'reject') {
    if (busy || !approval || (decision === 'approve' && !run.report)) return
    setSubmitting(true)
    setMessage(null)
    try {
      const result = await runStore.mutate(run.id, () => api.decideApproval(run.id, approval.id, decision))
      if (result) onDecision?.(result)
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : t('runs.actionFailed'))
    } finally { setSubmitting(false) }
  }

  return (
    <section className="card approvalcard" aria-label={t('runs.approval')} aria-busy={busy}>
      <div className="decision__heading">
        <span className="decision__icon"><Icon name="shield" size={22} /></span>
        <div><p className="eyebrow">{t('cockpit.humanDecision')}</p><h3 className="card__title">{t('runs.approval')}</h3></div>
      </div>
      <p className="decision__intro">{t('cockpit.approvalIntro')}</p>
      {run.report ? <p className="decision__artifact"><span dir="auto">{run.report.name}</span> · {t('cockpit.version', { version: formatNumber(run.report.version) })}</p> : null}
      {run.report ? <details className="decision__preview">
        <summary>{t('cockpit.exactReport')}</summary>
        <p className="card__meta">{t('cockpit.previewIncludesEvidence')}</p>
        <pre className="runreport__content" tabIndex={0} aria-label={t('cockpit.exactReport')} dir={run.report_language === 'ar' ? 'rtl' : 'ltr'} lang={run.report_language}>{run.report.content}</pre>
      </details> : <p role="status">{t('cockpit.reportUnavailable')}</p>}
      <dl className="decision__facts">
        {[
          [t('runs.action'), approval.action, run.report_language], [t('runs.target'), approval.target, 'en'],
          [t('runs.risk'), approval.risk === 'high' ? t('runs.riskHigh') : approval.risk, undefined],
          [t('runs.impact'), approval.impact, run.report_language], [t('runs.reversibility'), approval.reversibility, run.report_language],
        ].map(([label, value, language]) => <div key={label}><dt>{label}</dt><dd dir="auto" lang={language}>{value}</dd></div>)}
      </dl>
      <p className="decision__binding"><Icon name="shield" size={14} />{t('cockpit.hashBound')}</p>
      {message ? <p role="alert" className="statusline statusline--error" dir="auto">{message}</p> : null}
      <div className="dialog__actions">
        <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => void decide('reject')}>{t('runs.reject')}</button>
        <button type="button" className="btn btn--primary" disabled={busy || !run.report} onClick={() => void decide('approve')}>
          {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}{busy ? t('cockpit.confirming') : t('runs.approve')}
        </button>
      </div>
    </section>
  )
}
