import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { api, ApiError, MAX_UPLOAD_BYTES } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import { formatBytes } from '../../shared/format'
import { formatLabel } from '../../shared/labels'
import type { DatasetSummary, UploadResult, Usage } from '../../shared/types'
import { ConnectorsPanel } from '../live/ConnectorsPanel'
import { MappingPanel } from './MappingPanel'
import { UploadPreview } from './UploadPreview'

/** The most datasets GET /api/datasets returns. */
const DATASET_PAGE = 50

const ACCEPT = '.csv,.tsv,.txt,.xlsx,.json,.jsonl,.ndjson'

interface DatasetsViewProps {
  onAnalyse: (dataset: DatasetSummary) => void
}

/** The datasets stored for this owner. Datasets are content-addressed on
 *  the server, so analysing one again sends nothing: the run refers to
 *  the stored copy by its id. */
export function DatasetsView({ onAnalyse }: DatasetsViewProps) {
  const { t, plural, locale, formatNumber, formatDate } = useI18n()
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [attempt, setAttempt] = useState(0)
  // Adding a dataset (ADR 0024): one file at a time, read and stored by
  // the server, which answers in the reader's language.
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<UploadResult | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  // Column mapping (ADR 0025): one dataset's columns at a time. A new
  // upload opens it straight away, without taking focus from the status.
  const [mapping, setMapping] = useState<{ id: string; focus: boolean } | null>(null)

  function closeMapping() {
    const id = mapping?.id
    setMapping(null)
    if (id) {
      // Back to the button that opened it, or the list if it came from an upload.
      requestAnimationFrame(() => document.getElementById(`dataset-columns-${id}`)?.focus())
    }
  }

  function updateDataset(changed: DatasetSummary) {
    setDatasets((list) =>
      list ? list.map((dataset) => (dataset.id === changed.id ? { ...dataset, ...changed } : dataset)) : list,
    )
  }

  async function addFile(file: File) {
    setOutcome(null)
    setUploadError(null)
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError(
        t('runs.tooBig', {
          name: file.name,
          size: formatNumber(file.size / 1_000_000, { maximumFractionDigits: 1 }),
          limit: formatNumber(MAX_UPLOAD_BYTES / 1_000_000),
        }),
      )
      return
    }
    setUploading(file.name)
    try {
      const result = await api.uploadDataset(file, locale)
      setOutcome(result)
      setMapping({ id: result.dataset.id, focus: false })
      // Refreshed in place: the list stays on screen while it updates.
      const [list, latest] = await Promise.allSettled([api.listDatasets(), api.usage()])
      if (list.status === 'fulfilled') setDatasets(list.value.datasets)
      if (latest.status === 'fulfilled') setUsage(latest.value)
    } catch (error) {
      setUploadError(error instanceof ApiError ? error.message : t('datasets.uploadFailed'))
    } finally {
      setUploading(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  useEffect(() => {
    let cancelled = false
    setFailed(null)
    setDatasets(null)
    api
      .listDatasets()
      .then((result) => !cancelled && setDatasets(result.datasets))
      .catch((error) => {
        if (!cancelled) {
          setFailed(error instanceof ApiError ? error.message : t('datasets.failed'))
        }
      })
    api
      .usage()
      .then((result) => !cancelled && setUsage(result))
      .catch(() => {
        /* the allowance line is a courtesy; the list stands without it */
      })
    return () => {
      cancelled = true
    }
    // `t` changes only with the locale; a retry is the key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])

  return (
    <section className="panel" aria-label={t('datasets.aria')}>
      <div className="panel__inner">
        <div className="panel__header">
          <div>
            <h2 className="panel__title">{t('datasets.title')}</h2>
            <p className="panel__desc">{t('datasets.desc')}</p>
          </div>
          <button
            type="button"
            className="btn btn--primary"
            disabled={uploading !== null}
            onClick={() => fileInput.current?.click()}
          >
            {uploading ? <span className="spinner" aria-hidden="true" /> : <Icon name="plus" size={16} />}
            {t('datasets.add')}
          </button>
          {/* Opened by the button above, which is what keyboard and
              screen-reader users reach; the input itself stays out of
              the tab order. */}
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            hidden
            tabIndex={-1}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void addFile(file)
            }}
          />
        </div>
        <p className="panel__note">{t('runs.fileHelp')}</p>
        <div role="status" aria-live="polite">
          {uploading ? (
            <p className="statusline">{t('datasets.uploading', { name: uploading })}</p>
          ) : outcome ? (
            <>
              <p className="statusline statusline--success" dir="auto">
                {outcome.created
                  ? t('datasets.addedOne', {
                      name: outcome.dataset.name,
                      rows: plural('runs.rows', outcome.dataset.row_count ?? 0),
                    })
                  : t('datasets.duplicate', { name: outcome.dataset.name })}
              </p>
              <UploadPreview result={outcome} />
              {outcome.warnings.length > 0 ? (
                <ul className="warnings">
                  {outcome.warnings.map((warning) => (
                    <li key={warning} dir="auto">
                      {warning}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
        </div>
        {uploadError ? (
          <p className="statusline statusline--error" role="alert" dir="auto">
            {uploadError}
          </p>
        ) : null}

        {usage ? (
          <p className="panel__note">
            {t('datasets.usage', {
              used: formatNumber(usage.datasets.used),
              limit: formatNumber(usage.datasets.limit),
              bytes: formatBytes(usage.dataset_bytes.used, formatNumber),
              bytesLimit: formatBytes(usage.dataset_bytes.limit, formatNumber),
            })}
          </p>
        ) : null}

        {mapping ? (
          <MappingPanel
            key={mapping.id}
            datasetId={mapping.id}
            focusOnOpen={mapping.focus}
            onClose={closeMapping}
            onChanged={updateDataset}
            onAnalyse={onAnalyse}
          />
        ) : null}

        {failed ? (
          <div className="card">
            <p className="statusline statusline--error" role="alert" dir="auto">
              {failed}
            </p>
            <button type="button" className="btn btn--ghost" onClick={() => setAttempt((n) => n + 1)}>
              <Icon name="refresh" size={16} />
              {t('common.tryAgain')}
            </button>
          </div>
        ) : !datasets ? (
          <div className="card" role="status" aria-label={t('datasets.loading')}>
            <div className="skeleton skeleton--line" />
            <div className="skeleton skeleton--line" />
            <div className="skeleton skeleton--line skeleton--short" />
          </div>
        ) : datasets.length === 0 ? (
          <div className="card empty">
            <div className="empty__icon">
              <Icon name="database" size={32} />
            </div>
            <h3 className="empty__title">{t('datasets.emptyTitle')}</h3>
            <p className="empty__text">{t('datasets.emptyText')}</p>
            <div className="empty__actions">
              <button
                type="button"
                className="btn btn--primary"
                disabled={uploading !== null}
                onClick={() => fileInput.current?.click()}
              >
                {t('datasets.add')}
              </button>
            </div>
          </div>
        ) : (
          <div className="card">
            <h3 className="card__title">{t('datasets.listTitle')}</h3>
            <ul className="datasets">
              {datasets.map((dataset) => (
                <li key={dataset.id} className="dataset">
                  <span className="dataset__icon">
                    <Icon name="database" size={18} />
                  </span>
                  <span className="dataset__body">
                    <span className="dataset__name" dir="auto">
                      {dataset.name}
                      {dataset.mapped ? (
                        <span className="dataset__tag">{t('mapping.mapped')}</span>
                      ) : null}
                    </span>
                    <span className="dataset__meta">
                      {dataset.source_format ? (
                        <>{formatLabel(t, dataset.source_format)} · </>
                      ) : null}
                      {dataset.row_count != null ? (
                        <>
                          <span className="dataset__figure">
                            {plural('runs.rows', dataset.row_count)}
                          </span>
                          {' · '}
                        </>
                      ) : null}
                      <span className="dataset__figure">
                        {formatBytes(dataset.byte_size, formatNumber)}
                      </span>
                      {' · '}
                      {t('datasets.added', { date: formatDate(dataset.created_at) })}
                      {' · '}
                      <span className="dataset__hash">
                        {t('datasets.fingerprint', { hash: dataset.sha256.slice(0, 8) })}
                      </span>
                    </span>
                  </span>
                  <span className="dataset__actions">
                    <button
                      type="button"
                      id={`dataset-columns-${dataset.id}`}
                      className="btn btn--ghost dataset__action"
                      aria-label={t('mapping.openAria', { name: dataset.name })}
                      aria-expanded={mapping?.id === dataset.id}
                      onClick={() => setMapping({ id: dataset.id, focus: true })}
                    >
                      {t('mapping.open')}
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost dataset__action"
                      aria-label={t('datasets.analyseAria', { name: dataset.name })}
                      onClick={() => onAnalyse(dataset)}
                    >
                      {t('datasets.analyse')}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            {datasets.length >= DATASET_PAGE ? (
              <p className="panel__note">
                {t('datasets.capped', { n: formatNumber(DATASET_PAGE) })}
              </p>
            ) : null}
          </div>
        )}

        <ConnectorsPanel />
      </div>
    </section>
  )
}

