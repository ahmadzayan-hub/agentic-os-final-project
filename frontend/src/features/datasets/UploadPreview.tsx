import { useI18n } from '../../i18n'
import type { UploadResult } from '../../shared/types'

export function UploadPreview({ result }: { result: UploadResult }) {
  const { t } = useI18n()
  return <details className="upload-preview"><summary>{t('datasets.previewTitle')}</summary>
    {result.sheets.length ? <p className="card__meta">{t('datasets.sheets')}: {result.sheets.map((sheet, index) => <span key={sheet}>{index ? ' · ' : ''}<bdi>{sheet}</bdi></span>)}</p> : null}
    <div className="evidence__table" role="region" aria-label={t('datasets.previewTitle')} tabIndex={0}><table className="datatable"><thead><tr>{result.columns.map((name) => <th key={name} scope="col" dir="auto">{name}</th>)}</tr></thead><tbody>{result.preview.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column} dir="auto">{cell}</td>)}</tr>)}</tbody></table></div>
  </details>
}
