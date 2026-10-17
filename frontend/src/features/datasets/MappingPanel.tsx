import { useEffect, useId, useRef, useState } from 'react'
import type { MessageKey } from '../../i18n'
import { useI18n } from '../../i18n'
import { api, ApiError } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import type {
  ColumnMapping,
  ColumnRole,
  DatasetDetail,
  DatasetSummary,
  DateOrder,
  Grain,
  MappingProblem,
} from '../../shared/types'

const ROLES: ColumnRole[] = ['measure', 'dimension', 'date', 'ignore']
const ORDERS: DateOrder[] = ['auto', 'day-first', 'month-first']
const GRAINS: Grain[] = ['auto', 'day', 'month', 'quarter', 'year']

interface MappingPanelProps {
  datasetId: string
  /** Move focus to the panel's heading when it opens from a button. */
  focusOnOpen: boolean
  onClose: () => void
  /** The dataset after a save or a clear, so the list can show it. */
  onChanged: (dataset: DatasetSummary) => void
  onAnalyse: (dataset: DatasetSummary) => void
}

function sameMapping(a: ColumnMapping | null, b: ColumnMapping | null): boolean {
  if (!a || !b) return a === b
  return (
    a.measure === b.measure &&
    a.dimension === b.dimension &&
    a.date_order === b.date_order &&
    a.grain === b.grain &&
    Object.keys(a.roles).length === Object.keys(b.roles).length &&
    Object.entries(a.roles).every(([column, role]) => b.roles[column] === role)
  )
}

/** A role change keeps the measure and breakdown pointing at columns that
 *  still have those roles, so the draft is never quietly invalid. */
export function withRole(draft: ColumnMapping, column: string, role: ColumnRole, order: string[]): ColumnMapping {
  const roles = { ...draft.roles, [column]: role }
  const measures = order.filter((c) => roles[c] === 'measure')
  const dimensions = order.filter((c) => roles[c] === 'dimension')
  const measure =
    draft.measure && roles[draft.measure] === 'measure' ? draft.measure : (measures[0] ?? null)
  const dimension =
    draft.dimension && roles[draft.dimension] === 'dimension'
      ? draft.dimension
      : (dimensions[0] ?? null)
  return { ...draft, roles, measure, dimension }
}

/** Say what each column is (ADR 0025). The server suggests, checks the
 *  mapping against every row, and explains any refusal by field; this
 *  panel shows that with an error summary and a message by each field. */
export function MappingPanel({ datasetId, focusOnOpen, onClose, onChanged, onAnalyse }: MappingPanelProps) {
  const { t, locale, formatNumber, formatDate } = useI18n()
  const base = useId()
  const heading = useRef<HTMLHeadingElement | null>(null)
  const summaryRef = useRef<HTMLDivElement | null>(null)
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [draft, setDraft] = useState<ColumnMapping | null>(null)
  const [busy, setBusy] = useState<'save' | 'clear' | null>(null)
  const [problems, setProblems] = useState<MappingProblem[]>([])
  const [summary, setSummary] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setDetail(null)
    setLoadError(null)
    api
      .getDataset(datasetId, locale)
      .then((result) => {
        if (cancelled) return
        if (!result?.dataset || !Array.isArray(result.columns) || !result.suggestion) {
          setLoadError(t('mapping.loadFailed'))
          return
        }
        setDetail(result)
        setDraft(result.mapping ?? result.suggestion)
      })
      .catch((error) => {
        if (!cancelled) setLoadError(error instanceof ApiError ? error.message : t('mapping.loadFailed'))
      })
    return () => {
      cancelled = true
    }
    // The reasons arrive in the reader's language, so a language change reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, attempt, locale])

  useEffect(() => {
    if (focusOnOpen) heading.current?.focus()
  }, [focusOnOpen, datasetId])

  // A refusal moves focus to its summary, which links to each field.
  useEffect(() => {
    if (summary) summaryRef.current?.focus()
  }, [summary, problems])

  const ids = {
    role: (index: number) => `${base}-role-${index}`,
    measure: `${base}-measure`,
    dimension: `${base}-dimension`,
    order: `${base}-order`,
    grain: `${base}-grain`,
  }

  const columns = detail?.columns ?? []
  const order = columns.map((c) => c.name)
  const fieldId = (problem: MappingProblem): string | null => {
    if (problem.field === 'roles') {
      const index = order.indexOf(problem.column ?? '')
      return index >= 0 ? ids.role(index) : null
    }
    if (problem.field === 'measure') return ids.measure
    if (problem.field === 'dimension') return ids.dimension
    if (problem.field === 'date_order') return ids.order
    return ids.grain
  }
  const errorsFor = (target: string) => problems.filter((p) => fieldId(p) === target)

  async function save() {
    if (!draft) return
    setBusy('save')
    setNotice(null)
    try {
      const result = await api.saveMapping(datasetId, draft, locale)
      setDetail(result)
      setDraft(result.mapping ?? result.suggestion)
      setProblems([])
      setSummary(null)
      setNotice(t('mapping.saved'))
      onChanged(result.dataset)
    } catch (error) {
      // A refusal names each field; anything else is one sentence.
      setProblems(error instanceof ApiError ? error.problems : [])
      setSummary(error instanceof ApiError ? error.message : t('mapping.saveFailed'))
    } finally {
      setBusy(null)
    }
  }

  async function clear() {
    setBusy('clear')
    setNotice(null)
    try {
      const result = await api.clearMapping(datasetId, locale)
      setDetail(result)
      setDraft(result.suggestion)
      setProblems([])
      setSummary(null)
      setNotice(t('mapping.cleared'))
      onChanged(result.dataset)
    } catch (error) {
      setSummary(error instanceof ApiError ? error.message : t('mapping.saveFailed'))
    } finally {
      setBusy(null)
    }
  }

  function changeRole(column: string, role: ColumnRole) {
    if (!draft) return
    setDraft(withRole(draft, column, role, order))
    setNotice(null)
  }

  const name = detail?.dataset.name ?? ''
  // Changed since it was loaded or saved; an untouched suggestion is not
  // a change, and the line above already says it is not saved.
  const dirty = Boolean(detail && draft && !sameMapping(draft, detail.mapping ?? detail.suggestion))
  const measures = draft ? order.filter((c) => draft.roles[c] === 'measure') : []
  const dimensions = draft ? order.filter((c) => draft.roles[c] === 'dimension') : []
  const hasDate = draft ? order.some((c) => draft.roles[c] === 'date') : false

  const errorText = (target: string) => {
    const found = errorsFor(target)
    return found.length ? (
      <p className="field-error" id={`${target}-error`} dir="auto">
        <Icon name="alert" size={14} />
        <span>{found.map((p) => p.message).join(' ')}</span>
      </p>
    ) : null
  }
  const described = (target: string, extra?: string) =>
    [extra, errorsFor(target).length ? `${target}-error` : null].filter(Boolean).join(' ') || undefined

  return (
    <section className="card mapping" aria-labelledby={`${base}-title`}>
      <div className="mapping__head">
        <h3 className="card__title" id={`${base}-title`} ref={heading} tabIndex={-1} dir="auto">
          {detail ? t('mapping.title', { name }) : t('mapping.loading')}
        </h3>
        <button type="button" className="iconbtn" aria-label={t('mapping.close')} onClick={onClose}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <p className="panel__desc">{t('mapping.desc')}</p>

      {loadError ? (
        <div>
          <p className="statusline statusline--error" role="alert" dir="auto">
            {loadError}
          </p>
          <button type="button" className="btn btn--ghost" onClick={() => setAttempt((n) => n + 1)}>
            <Icon name="refresh" size={16} />
            {t('common.tryAgain')}
          </button>
        </div>
      ) : !detail || !draft ? (
        <div role="status" aria-label={t('mapping.loading')}>
          <div className="skeleton skeleton--line" />
          <div className="skeleton skeleton--line" />
          <div className="skeleton skeleton--line skeleton--short" />
        </div>
      ) : (
        <>
          <p className="panel__note">
            {detail.mapping && detail.dataset.mapping_updated_at
              ? t('mapping.stateSaved', { date: formatDate(detail.dataset.mapping_updated_at) })
              : t('mapping.stateSuggested')}
            {detail.profiled_rows < detail.row_count
              ? ` ${t('mapping.sampled', {
                  n: formatNumber(detail.profiled_rows),
                  total: formatNumber(detail.row_count),
                })}`
              : ''}
          </p>

          {summary ? (
            <div className="error-summary" role="alert" tabIndex={-1} ref={summaryRef}>
              <h4 className="error-summary__title">{t('mapping.errorTitle')}</h4>
              <p dir="auto">{summary}</p>
              {problems.length ? (
                <ul className="error-summary__list">
                  {problems.map((problem, index) => {
                    const target = fieldId(problem)
                    return (
                      <li key={`${problem.field}-${problem.column}-${index}`} dir="auto">
                        {target ? (
                          <a
                            href={`#${target}`}
                            onClick={(event) => {
                              event.preventDefault()
                              document.getElementById(target)?.focus()
                            }}
                          >
                            {problem.message}
                          </a>
                        ) : (
                          problem.message
                        )}
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </div>
          ) : null}

          <h4 className="mapping__subtitle">{t('mapping.preview')}</h4>
          <div
            className="mapping__preview"
            role="region"
            aria-label={t('mapping.previewAria', { name })}
            tabIndex={0}
          >
            <table className="datatable mapping__table">
              <thead>
                <tr>
                  {order.map((column) => (
                    <th key={column} scope="col" dir="auto">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detail.preview.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex} dir="auto">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 className="mapping__subtitle">{t('mapping.columnsTitle')}</h4>
          <ul className="mapping__columns">
            {columns.map((column, index) => {
              const id = ids.role(index)
              const invalid = errorsFor(id).length > 0
              return (
                <li key={column.name} className="mapping__column">
                  <div className="mapping__about">
                    <label className="mapping__name" htmlFor={id} dir="auto">
                      {column.name}
                    </label>
                    <span className="mapping__meta" id={`${id}-reason`}>
                      {t(`coltype.${column.type}` as MessageKey)} · <span dir="auto">{column.reason}</span>
                      {column.examples.length ? (
                        <>
                          {' · '}
                          <span dir="auto">{t('mapping.examples', { values: column.examples.join(', ') })}</span>
                        </>
                      ) : null}
                    </span>
                  </div>
                  <div className="mapping__choice">
                    <select
                      id={id}
                      className="field__select"
                      value={draft.roles[column.name] ?? 'ignore'}
                      aria-invalid={invalid || undefined}
                      aria-describedby={described(id, `${id}-reason`)}
                      onChange={(event) => changeRole(column.name, event.target.value as ColumnRole)}
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {t(`role.${role}` as MessageKey)}
                        </option>
                      ))}
                    </select>
                    {errorText(id)}
                  </div>
                </li>
              )
            })}
          </ul>

          <div className="mapping__options">
            <div className="field">
              <label className="field__label" htmlFor={ids.measure}>
                {t('mapping.measure')}
              </label>
              <span className="field__help" id={`${ids.measure}-help`}>
                {t('mapping.measureHelp')}
              </span>
              <select
                id={ids.measure}
                className="field__select"
                value={draft.measure ?? ''}
                aria-invalid={errorsFor(ids.measure).length > 0 || undefined}
                aria-describedby={described(ids.measure, `${ids.measure}-help`)}
                onChange={(event) => setDraft({ ...draft, measure: event.target.value || null })}
              >
                {measures.length === 0 ? <option value="">{t('mapping.noMeasure')}</option> : null}
                {measures.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>
              {errorText(ids.measure)}
            </div>
            <div className="field">
              <label className="field__label" htmlFor={ids.dimension}>
                {t('mapping.dimension')}
              </label>
              <select
                id={ids.dimension}
                className="field__select"
                value={draft.dimension ?? ''}
                aria-invalid={errorsFor(ids.dimension).length > 0 || undefined}
                aria-describedby={described(ids.dimension)}
                onChange={(event) => setDraft({ ...draft, dimension: event.target.value || null })}
              >
                <option value="">{t('mapping.noDimension')}</option>
                {dimensions.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>
              {errorText(ids.dimension)}
            </div>
            {hasDate ? (
              <>
                <div className="field">
                  <label className="field__label" htmlFor={ids.order}>
                    {t('mapping.dateOrder')}
                  </label>
                  <select
                    id={ids.order}
                    className="field__select"
                    value={draft.date_order}
                    aria-invalid={errorsFor(ids.order).length > 0 || undefined}
                    aria-describedby={described(ids.order)}
                    onChange={(event) => setDraft({ ...draft, date_order: event.target.value as DateOrder })}
                  >
                    {ORDERS.map((value) => (
                      <option key={value} value={value}>
                        {t(`order.${value}` as MessageKey)}
                      </option>
                    ))}
                  </select>
                  {errorText(ids.order)}
                </div>
                <div className="field">
                  <label className="field__label" htmlFor={ids.grain}>
                    {t('mapping.grain')}
                  </label>
                  <select
                    id={ids.grain}
                    className="field__select"
                    value={draft.grain}
                    aria-invalid={errorsFor(ids.grain).length > 0 || undefined}
                    aria-describedby={described(ids.grain)}
                    onChange={(event) => setDraft({ ...draft, grain: event.target.value as Grain })}
                  >
                    {GRAINS.map((value) => (
                      <option key={value} value={value}>
                        {t(`grain.${value}` as MessageKey)}
                      </option>
                    ))}
                  </select>
                  {errorText(ids.grain)}
                </div>
              </>
            ) : null}
          </div>

          <div className="mapping__actions">
            <button type="button" className="btn btn--primary" disabled={busy !== null} onClick={() => void save()}>
              {busy === 'save' ? <span className="spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}
              {busy === 'save' ? t('mapping.saving') : t('mapping.save')}
            </button>
            {detail.mapping ? (
              <button type="button" className="btn btn--ghost" disabled={busy !== null} onClick={() => void clear()}>
                {t('mapping.clear')}
              </button>
            ) : null}
            {/* Says which columns a run will use: the saved mapping, or
                automatic detection. Unsaved changes are never used. */}
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy !== null}
              onClick={() => onAnalyse(detail.dataset)}
            >
              {detail.mapping ? t('mapping.analyseMapped') : t('mapping.analyseAuto')}
            </button>
          </div>
          <div role="status" aria-live="polite">
            {notice ? (
              <p className="statusline statusline--success" dir="auto">
                {notice}
              </p>
            ) : dirty ? (
              <p className="statusline">{t('mapping.unsaved')}</p>
            ) : null}
          </div>
        </>
      )}
    </section>
  )
}
