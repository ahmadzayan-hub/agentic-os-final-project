/** Several datasets in one run (ADR 0030): pick a dataset to join, the
 *  key columns on each side, what happens to rows without a match, and
 *  preview the merge before starting. The preview runs the server's own
 *  stages, so what it shows is what the run will do. */
import { useEffect, useRef, useState } from 'react'
import { usePack } from '../../i18n/pack'
import { joinMessages } from './messages'
import { api, ApiError } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import type { DatasetSummary, JoinPreview, JoinSpec, MappingProblem } from '../../shared/types'

export const MAX_JOINS = 4
const MAX_KEYS = 3

interface JoinBuilderProps {
  primaryId: string | null
  datasets: DatasetSummary[] | null
  disabled: boolean
  joins: JoinSpec[]
  breakdown: string
  onChange: (joins: JoinSpec[], breakdown: string) => void
}

/** A key pair to start from: a column both tables share by name, else
 *  the first column of each. */
function suggestKey(left: string[], right: string[]) {
  const shared = left.find((name) => right.some((other) => other.toLowerCase() === name.toLowerCase()))
  if (shared) return { left: shared, right: right.find((other) => other.toLowerCase() === shared.toLowerCase())! }
  return { left: left[0] ?? '', right: right[0] ?? '' }
}

export function JoinBuilder({ primaryId, datasets, disabled, joins, breakdown, onChange }: JoinBuilderProps) {
  const { t, locale, formatNumber } = usePack(joinMessages)
  const [columns, setColumns] = useState<Record<string, string[]>>({})
  const [preview, setPreview] = useState<JoinPreview | null>(null)
  const [previewed, setPreviewed] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState<{ message: string; problems: MappingProblem[] } | null>(null)
  const requested = useRef(new Set<string>())

  // Each dataset's column names, read once from the dataset detail.
  useEffect(() => {
    const wanted = [primaryId, ...joins.map((join) => join.dataset_id)].filter(
      (id): id is string => Boolean(id) && !requested.current.has(id as string),
    )
    for (const id of wanted) {
      requested.current.add(id)
      api
        .getDataset(id, locale)
        .then((detail) => setColumns((known) => ({ ...known, [id]: detail.columns.map((c) => c.name) })))
        .catch(() => requested.current.delete(id))
    }
  }, [primaryId, joins, locale])

  // A new main dataset starts the joins again: its columns are different.
  const lastPrimary = useRef(primaryId)
  useEffect(() => {
    if (lastPrimary.current === primaryId) return
    lastPrimary.current = primaryId
    setPreview(null)
    setError(null)
    if (joins.length) onChange([], '')
  }, [primaryId, joins.length, onChange])

  const others = (datasets ?? []).filter((d) => d.id !== primaryId)
  const signature = JSON.stringify([primaryId, joins, breakdown])
  const stale = preview !== null && previewed !== signature

  function update(index: number, change: Partial<JoinSpec>) {
    onChange(joins.map((join, i) => (i === index ? { ...join, ...change } : join)), breakdown)
  }

  /** The columns a join's key may use on the main side: the main table's,
   *  then those the joins before it added. */
  function leftColumns(index: number) {
    const names = [...(columns[primaryId ?? ''] ?? [])]
    joins.slice(0, index).forEach((join) => {
      const rights = join.keys.map((key) => key.right)
      for (const name of columns[join.dataset_id] ?? []) if (!rights.includes(name) && !names.includes(name)) names.push(name)
    })
    return names
  }

  function chooseDataset(index: number, id: string) {
    const right = columns[id]
    update(index, { dataset_id: id, keys: right ? [suggestKey(leftColumns(index), right)] : [{ left: '', right: '' }] })
  }

  // Columns that arrive after a dataset is chosen fill an empty key.
  useEffect(() => {
    let changed = false
    const next = joins.map((join, index) => {
      const right = columns[join.dataset_id]
      if (!right || join.keys.some((key) => key.left || key.right)) return join
      changed = true
      return { ...join, keys: [suggestKey(leftColumns(index), right)] }
    })
    if (changed) onChange(next, breakdown)
  }, [columns, joins, breakdown, onChange])

  async function runPreview() {
    if (!primaryId) return
    setPreviewing(true)
    setError(null)
    try {
      const result = await api.previewJoins(primaryId, joins, breakdown || null, locale)
      setPreview(result)
      setPreviewed(signature)
    } catch (caught) {
      setPreview(null)
      setError(
        caught instanceof ApiError
          ? { message: caught.message, problems: caught.problems }
          : { message: t('joins.failed'), problems: [] },
      )
    } finally {
      setPreviewing(false)
    }
  }

  const percent = (value: number) => formatNumber(value, { style: 'percent', maximumFractionDigits: 1 })
  const breakdownChoices = preview?.breakdown_choices ?? (breakdown ? [breakdown] : [])

  return (
    <fieldset className="joinbuilder" disabled={disabled}>
      <legend className="field__label">{t('joins.title')}</legend>
      <p className="field__help">{t('joins.help')}</p>
      {!primaryId ? <p className="field__help">{t('joins.needPrimary')}</p> : null}
      {joins.map((join, index) => {
        const right = columns[join.dataset_id] ?? []
        const left = leftColumns(index)
        const idBase = `join-${index}`
        return (
          <div className="joinbuilder__item" role="group" aria-labelledby={`${idBase}-title`} key={index}>
            <p className="card__title" id={`${idBase}-title`}>
              {t('joins.item', { n: formatNumber(index + 1) })}
            </p>
            <div className="field">
              <label className="field__label" htmlFor={`${idBase}-dataset`}>
                {t('joins.dataset')}
              </label>
              <select
                id={`${idBase}-dataset`}
                className="field__select"
                value={join.dataset_id}
                onChange={(event) => chooseDataset(index, event.target.value)}
              >
                {join.dataset_id ? null : <option value="">{t('joins.pick')}</option>}
                {others.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            {join.keys.map((key, keyIndex) => (
              <div className="joinbuilder__key" key={keyIndex}>
                <div className="field">
                  <label className="field__label" htmlFor={`${idBase}-left-${keyIndex}`}>
                    {t('joins.mainColumn')}
                  </label>
                  <select
                    id={`${idBase}-left-${keyIndex}`}
                    className="field__select"
                    dir="auto"
                    value={key.left}
                    onChange={(event) =>
                      update(index, {
                        keys: join.keys.map((k, i) => (i === keyIndex ? { ...k, left: event.target.value } : k)),
                      })
                    }
                  >
                    {key.left ? null : <option value="">—</option>}
                    {left.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label className="field__label" htmlFor={`${idBase}-right-${keyIndex}`}>
                    {t('joins.joinedColumn')}
                  </label>
                  <select
                    id={`${idBase}-right-${keyIndex}`}
                    className="field__select"
                    dir="auto"
                    value={key.right}
                    onChange={(event) =>
                      update(index, {
                        keys: join.keys.map((k, i) => (i === keyIndex ? { ...k, right: event.target.value } : k)),
                      })
                    }
                  >
                    {key.right ? null : <option value="">—</option>}
                    {right.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
                {join.keys.length > 1 ? (
                  <button
                    type="button"
                    className="btn btn--subtle"
                    aria-label={t('joins.removeKey', { n: formatNumber(keyIndex + 1) })}
                    onClick={() => update(index, { keys: join.keys.filter((_, i) => i !== keyIndex) })}
                  >
                    <Icon name="x" size={14} />
                  </button>
                ) : null}
              </div>
            ))}
            {join.keys.length < MAX_KEYS ? (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => update(index, { keys: [...join.keys, { left: '', right: '' }] })}
              >
                {t('joins.addKey')}
              </button>
            ) : null}
            <div className="field">
              <span className="field__label" id={`${idBase}-how`}>
                {t('joins.how')}
              </span>
              <div className="segmented" role="group" aria-labelledby={`${idBase}-how`}>
                {(['left', 'inner'] as const).map((how) => (
                  <button
                    key={how}
                    type="button"
                    className="segmented__option"
                    aria-pressed={join.how === how}
                    onClick={() => update(index, { how })}
                  >
                    {t(how === 'left' ? 'joins.keepAll' : 'joins.onlyMatched')}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              className="btn btn--subtle"
              onClick={() => onChange(joins.filter((_, i) => i !== index), breakdown)}
            >
              {t('joins.remove', { n: formatNumber(index + 1) })}
            </button>
          </div>
        )
      })}
      {primaryId && others.length === 0 ? <p className="field__help">{t('joins.noOthers')}</p> : null}
      <div>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={!primaryId || others.length === 0 || joins.length >= MAX_JOINS}
          onClick={() => onChange([...joins, { dataset_id: '', keys: [{ left: '', right: '' }], how: 'left' }], breakdown)}
        >
          <Icon name="plus" size={16} />
          {t('joins.add')}
        </button>
      </div>
      {joins.length ? (
        <>
          <div className="field">
            <label className="field__label" htmlFor="join-breakdown">
              {t('joins.breakdown')}
            </label>
            <select
              id="join-breakdown"
              className="field__select"
              dir="auto"
              value={breakdown}
              onChange={(event) => onChange(joins, event.target.value)}
            >
              <option value="">{t('joins.breakdownDefault')}</option>
              {breakdownChoices.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            {preview ? null : <span className="field__help">{t('joins.breakdownHelp')}</span>}
          </div>
          <div>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={previewing || joins.some((join) => !join.dataset_id || join.keys.some((k) => !k.left || !k.right))}
              onClick={() => void runPreview()}
            >
              {previewing ? <span className="spinner" aria-hidden="true" /> : <Icon name="search" size={16} />}
              {previewing ? t('joins.previewing') : t('joins.preview')}
            </button>
          </div>
        </>
      ) : null}
      <div role="status" aria-live="polite">
        {stale ? <p className="field__help">{t('joins.stale')}</p> : null}
        {preview ? (
          <div className="joinbuilder__result">
            <p>
              {t('joins.summary', {
                before: formatNumber(preview.rows_before),
                after: formatNumber(preview.rows_after),
                added: formatNumber(preview.added_columns.length),
              })}
            </p>
            <ul className={preview.joins.some((record) => record.unmatched) ? 'warnings' : 'joinbuilder__list'}>
              {preview.joins.map((record) => (
                <li key={record.alias} dir="auto">
                  {t('joins.matched', {
                    name: record.name,
                    matched: formatNumber(record.matched),
                    total: formatNumber(record.rows_in),
                    pct: percent(record.coverage),
                  })}
                  {record.unmatched_keys.length ? <> {t('joins.unmatched', { keys: record.unmatched_keys.join(', ') })}</> : null}
                  {record.lookup_unused ? <> {t('joins.unused', { n: formatNumber(record.lookup_unused), name: record.name })}</> : null}
                  {Object.keys(record.renamed).length ? (
                    <> {t('joins.renamed', { list: Object.entries(record.renamed).map(([a, b]) => `${a} → ${b}`).join(', ') })}</>
                  ) : null}
                  {record.how === 'inner' && record.unmatched ? <> {t('joins.inner', { n: formatNumber(record.rows_out) })}</> : null}
                </li>
              ))}
            </ul>
            {preview.personal_data.length ? (
              <p className="warnings" dir="auto">
                {t('joins.personal', { list: preview.personal_data.map((p) => `${p.dataset}: ${p.column}`).join(', ') })}
              </p>
            ) : null}
            <div className="evidence__table" role="region" aria-label={t('joins.previewTable')} tabIndex={0}>
              <table className="datatable">
                <thead>
                  <tr>
                    {preview.columns.map((name) => (
                      <th key={name} scope="col" dir="auto">
                        {name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.preview.map((row, index) => (
                    <tr key={index}>
                      {row.map((cell, column) => (
                        <td key={column} dir="auto">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
      {error ? (
        <div role="alert" className="statusline statusline--error">
          <p dir="auto">{error.message}</p>
          {error.problems.length ? (
            <ul>
              {error.problems.map((problem, index) => (
                <li key={index} dir="auto">
                  {problem.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </fieldset>
  )
}
