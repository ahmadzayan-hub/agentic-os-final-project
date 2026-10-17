import { useI18n } from '../../i18n'
import { Dialog } from '../../shared/components/Dialog'
import { Icon } from '../../shared/components/Icon'
import type { RunDetail, RunTask } from '../../shared/types'
import { reportCalculations } from './evidence'

export function EvidencePanel({ run, task, onClose }: {
  run: RunDetail
  task: RunTask
  onClose: () => void
}) {
  const { t } = useI18n()
  const section = run.reports.find((report) => report.type === task.role)
  const rows = reportCalculations(section?.content ?? run.report?.content ?? '')
  const reportLanguage = run.report_language === 'ar' ? 'ar' : 'en'
  return (
    <Dialog title={t('cockpit.why')} onClose={onClose} wide initialFocus="panel">
      <div className="evidence__context"><span dir="auto">{run.dataset_name}</span><span dir="auto" lang={reportLanguage}>{task.title}</span></div>
      {task.summary ? <p dir="auto" lang={reportLanguage} className="evidence__summary">{task.summary}</p> : null}
      <h3 className="card__title">{t('cockpit.claims')}</h3>
      {task.claims.length ? task.claims.map((claim) => (
        <article className="evidence__claim" key={claim.id}>
          <p dir="auto" lang={reportLanguage}>{claim.text}</p>
          <p className="card__meta">{t('cockpit.references')}</p>
          <ul className="evidence__refs">{claim.evidence.map((id) => <li key={id}><code dir="ltr" lang="en">{id}</code></li>)}</ul>
        </article>
      )) : <p className="card__meta">{t('cockpit.noClaims')}</p>}
      {task.quality_checks.length ? <><h3 className="card__title">{t('cockpit.checks')}</h3><ul className="evidence__checks">
        {task.quality_checks.map((check) => <li key={check.name}><Icon name={check.passed ? 'check' : 'alert'} size={16} /><span><strong dir="ltr" lang="en">{check.name}</strong> · {check.passed ? t('cockpit.passed') : t('cockpit.notPassed')}<span className="controlrow__help" dir="auto" lang={reportLanguage}>{check.detail}</span></span></li>)}
      </ul></> : null}
      <h3 className="card__title">{t('cockpit.calculations')}</h3>
      <p className="card__meta">{t('cockpit.calculationScope')}</p>
      {rows.length ? <div className="evidence__table" role="region" aria-label={t('cockpit.calculations')} tabIndex={0}>
        <table className="datatable"><thead><tr><th scope="col">{t('cockpit.figure')}</th><th scope="col">{t('runs.chartValue')}</th><th scope="col">{t('cockpit.method')}</th></tr></thead><tbody>
          {rows.map((row, index) => <tr key={`${row.name}-${index}`}><th scope="row" dir="auto">{row.name}</th><td dir="auto">{row.value}</td><td dir="auto">{row.method}</td></tr>)}
        </tbody></table></div> : <p className="card__meta">{t('cockpit.calculationsPending')}</p>}
      <div className="dialog__actions"><button className="btn btn--primary" type="button" onClick={onClose}>{t('common.close')}</button></div>
    </Dialog>
  )
}
