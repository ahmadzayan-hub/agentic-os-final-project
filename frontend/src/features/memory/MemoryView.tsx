import { useMemo, useState } from 'react'
import { useI18n } from '../../i18n'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { Icon } from '../../shared/components/Icon'
import { categoryLabel } from '../../shared/labels'
import type { OperationOutcome } from '../../app/store'
import type { MemoryEntry } from '../../shared/types'

const CATEGORY_OPTIONS = ['general', 'profile', 'work', 'projects', 'preferences']

interface MemoryViewProps {
  entries: MemoryEntry[]
  disabled: boolean
  onAdd: (information: string, category?: string) => Promise<OperationOutcome>
  onUpdate: (key: string, information: string, category?: string) => Promise<OperationOutcome>
  onDelete: (key: string) => Promise<OperationOutcome>
  onClearAll: () => Promise<OperationOutcome>
  onExport: () => Promise<OperationOutcome>
  onClearHistory: () => void
}

export function MemoryView({
  entries,
  disabled,
  onAdd,
  onUpdate,
  onDelete,
  onClearAll,
  onExport,
  onClearHistory,
}: MemoryViewProps) {
  const { t, tx, formatDate } = useI18n()
  const [draft, setDraft] = useState('')
  const [draftCategory, setDraftCategory] = useState('general')
  const [query, setQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [editCategory, setEditCategory] = useState('general')
  const [statusMessage, setStatusMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmingClear, setConfirmingClear] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState<MemoryEntry | null>(null)

  const categories = useMemo(() => {
    const present = new Set(entries.map((entry) => entry.category))
    return ['all', ...Array.from(present).sort()]
  }, [entries])

  const needle = query.trim().toLowerCase()
  const visible = entries.filter(
    (entry) =>
      (categoryFilter === 'all' || entry.category === categoryFilter) &&
      (!needle ||
        entry.text.toLowerCase().includes(needle) ||
        entry.key.toLowerCase().includes(needle)),
  )

  async function run(action: () => Promise<OperationOutcome>) {
    setBusy(true)
    const outcome = await action()
    setStatusMessage({ ok: outcome.ok, text: outcome.message })
    setBusy(false)
    return outcome
  }

  async function submitAdd(event: React.FormEvent) {
    event.preventDefault()
    const information = draft.trim()
    if (!information) {
      setStatusMessage({ ok: false, text: t('memory.emptyFirst') })
      return
    }
    const outcome = await run(() => onAdd(information, draftCategory))
    if (outcome.ok) setDraft('')
  }

  function beginEdit(entry: MemoryEntry) {
    setEditingKey(entry.key)
    setEditDraft(entry.text)
    setEditCategory(entry.category)
  }

  async function submitEdit(event: React.FormEvent) {
    event.preventDefault()
    if (!editingKey) return
    const information = editDraft.trim()
    if (!information) {
      setStatusMessage({ ok: false, text: t('memory.emptyText') })
      return
    }
    const outcome = await run(() => onUpdate(editingKey, information, editCategory))
    if (outcome.ok) setEditingKey(null)
  }

  const editCategoryOptions = CATEGORY_OPTIONS.includes(editCategory)
    ? CATEGORY_OPTIONS
    : [editCategory, ...CATEGORY_OPTIONS]

  return (
    <section className="panel" aria-label={t('memory.aria')}>
      <div className="panel__inner panel__inner--split">
        <div className="panel__column">
          <div className="panel__header">
            <div>
              <h2 className="panel__title">{t('memory.title')}</h2>
              <p className="panel__desc">{t('memory.desc')}</p>
            </div>
          </div>

          <div className="card">
            <form className="memory__form" onSubmit={submitAdd}>
              <label className="visually-hidden" htmlFor="memory-input">
                {t('memory.inputLabel')}
              </label>
              <input
                id="memory-input"
                className="field__input"
                type="text"
                dir="auto"
                placeholder={t('memory.placeholder')}
                value={draft}
                maxLength={4000}
                onChange={(event) => setDraft(event.target.value)}
                disabled={busy || disabled}
              />
              <label className="visually-hidden" htmlFor="memory-category">
                {t('memory.category')}
              </label>
              <select
                id="memory-category"
                className="field__select memory__categoryselect"
                value={draftCategory}
                onChange={(event) => setDraftCategory(event.target.value)}
                disabled={busy || disabled}
              >
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {categoryLabel(t, option)}
                  </option>
                ))}
              </select>
              <button type="submit" className="btn btn--primary" disabled={busy || disabled}>
                {busy ? (
                  <span className="spinner" aria-hidden="true" />
                ) : (
                  <Icon name="plus" size={16} />
                )}
                {t('memory.add')}
              </button>
            </form>

            {entries.length > 0 ? (
              <>
                <div className="memory__search">
                  <label className="visually-hidden" htmlFor="memory-search">
                    {t('memory.searchLabel')}
                  </label>
                  <input
                    id="memory-search"
                    className="field__input"
                    type="search"
                    dir="auto"
                    placeholder={t('memory.searchPlaceholder')}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </div>
                {categories.length > 2 ? (
                  <div className="chips" role="group" aria-label={t('memory.filterAria')}>
                    {categories.map((category) => (
                      <button
                        key={category}
                        type="button"
                        className="chip"
                        aria-pressed={categoryFilter === category}
                        onClick={() => setCategoryFilter(category)}
                      >
                        {category === 'all' ? t('common.all') : categoryLabel(t, category)}
                      </button>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}

            <p
              className={`statusline ${
                statusMessage ? (statusMessage.ok ? 'statusline--success' : 'statusline--error') : ''
              }`}
              role="status"
              aria-live="polite"
              dir="auto"
            >
              {statusMessage?.text ?? ''}
            </p>

            {entries.length === 0 ? (
              <div className="empty">
                <div className="empty__icon">
                  <Icon name="memory" size={32} />
                </div>
                <p>{t('memory.none')}</p>
              </div>
            ) : visible.length === 0 ? (
              <p className="empty">{t('memory.noMatch')}</p>
            ) : (
              <ul className="memory__list">
                {visible.map((entry) =>
                  editingKey === entry.key ? (
                    <li key={entry.key} className="memory__item memory__item--editing">
                      <form className="memory__editform" onSubmit={submitEdit}>
                        <label className="visually-hidden" htmlFor={`edit-${entry.key}`}>
                          {t('memory.editLabel', { key: entry.key })}
                        </label>
                        <input
                          id={`edit-${entry.key}`}
                          className="field__input"
                          type="text"
                          dir="auto"
                          value={editDraft}
                          maxLength={4000}
                          autoFocus
                          onChange={(event) => setEditDraft(event.target.value)}
                          disabled={busy}
                        />
                        <label className="visually-hidden" htmlFor={`edit-category-${entry.key}`}>
                          {t('memory.editCategory', { key: entry.key })}
                        </label>
                        <select
                          id={`edit-category-${entry.key}`}
                          className="field__select memory__categoryselect"
                          value={editCategory}
                          onChange={(event) => setEditCategory(event.target.value)}
                          disabled={busy}
                        >
                          {editCategoryOptions.map((option) => (
                            <option key={option} value={option}>
                              {categoryLabel(t, option)}
                            </option>
                          ))}
                        </select>
                        <button type="submit" className="btn btn--primary" disabled={busy}>
                          {t('common.save')}
                        </button>
                        <button
                          type="button"
                          className="btn btn--ghost"
                          onClick={() => setEditingKey(null)}
                          disabled={busy}
                        >
                          {t('common.cancel')}
                        </button>
                      </form>
                    </li>
                  ) : (
                    <li key={entry.key} className="memory__item">
                      <div className="memory__body">
                        <p className="memory__text" dir="auto">
                          {entry.text}
                        </p>
                        <p className="memory__meta">
                          <span className={`memory__category memory__category--${entry.category}`}>
                            {categoryLabel(t, entry.category)}
                          </span>
                          <span className="memory__key" dir="ltr">
                            {entry.key}
                          </span>
                          {entry.updated ? (
                            <span>{t('memory.updated', { date: formatDate(entry.updated) })}</span>
                          ) : null}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="iconbtn"
                        aria-label={t('memory.editLabel', { key: entry.key })}
                        onClick={() => beginEdit(entry)}
                        disabled={busy || disabled}
                      >
                        <Icon name="edit" size={16} />
                      </button>
                      <button
                        type="button"
                        className="iconbtn iconbtn--danger"
                        aria-label={t('memory.forgetLabel', { key: entry.key })}
                        onClick={() => setConfirmingDelete(entry)}
                        disabled={busy || disabled}
                      >
                        <Icon name="trash" size={16} />
                      </button>
                    </li>
                  ),
                )}
              </ul>
            )}

            <p className="privacy-note">
              <Icon name="shield" size={14} />
              <span>{tx('memory.stored', { code: <code dir="ltr">data/memory.json</code> })}</span>
            </p>
          </div>
        </div>

        <div className="panel__column panel__column--side">
          <div className="card">
            <h3 className="card__title">{t('memory.controls')}</h3>
            <ul className="controls__list">
              <li>
                <button
                  type="button"
                  className="controlrow"
                  onClick={() => void run(onExport)}
                  disabled={busy || disabled}
                >
                  <Icon name="download" size={17} />
                  <span>
                    <span className="controlrow__label">{t('memory.export')}</span>
                    <span className="controlrow__help">{t('memory.exportHelp')}</span>
                  </span>
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className="controlrow"
                  onClick={onClearHistory}
                  disabled={busy || disabled}
                >
                  <Icon name="clock" size={17} />
                  <span>
                    <span className="controlrow__label">{t('memory.clearHistory')}</span>
                    <span className="controlrow__help">{t('memory.clearHistoryHelp')}</span>
                  </span>
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className="controlrow controlrow--danger"
                  onClick={() => setConfirmingClear(true)}
                  disabled={busy || disabled || entries.length === 0}
                >
                  <Icon name="trash" size={17} />
                  <span>
                    <span className="controlrow__label">{t('memory.deleteAll')}</span>
                    <span className="controlrow__help">{t('memory.deleteAllHelp')}</span>
                  </span>
                </button>
              </li>
            </ul>
            <p className="privacy-note">{t('memory.destructive')}</p>
          </div>
        </div>
      </div>

      {confirmingDelete ? (
        <ConfirmDialog
          title={t('memory.forgetTitle', { key: confirmingDelete.key })}
          message={t('memory.forgetMessage', { text: confirmingDelete.text })}
          confirmLabel={t('memory.forgetConfirm')}
          busy={busy}
          onCancel={() => setConfirmingDelete(null)}
          onConfirm={() => {
            const key = confirmingDelete.key
            void run(() => onDelete(key)).then(() => setConfirmingDelete(null))
          }}
        />
      ) : null}

      {confirmingClear ? (
        <ConfirmDialog
          title={t('memory.deleteAllTitle')}
          message={t('memory.deleteAllMessage')}
          confirmLabel={t('memory.deleteAll')}
          busy={busy}
          onCancel={() => setConfirmingClear(false)}
          onConfirm={() => {
            void run(onClearAll).then(() => setConfirmingClear(false))
          }}
        />
      ) : null}
    </section>
  )
}
