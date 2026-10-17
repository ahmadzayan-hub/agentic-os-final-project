/** Live sources (ADR 0034): saved https addresses that snapshot into
 *  datasets, now or on a schedule. Each row follows the event stream, so
 *  a refresh the worker made appears without reloading. */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { usePack } from '../../i18n/pack'
import { ApiError } from '../../shared/api'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { Icon } from '../../shared/components/Icon'
import { formatLabel, stateLabel } from '../../shared/labels'
import { routeHash } from '../../app/routing'
import { connectorsApi } from './connectors'
import type { Connector } from './connectors'
import { useLive } from './live'
import { LiveBadge } from './LiveBadge'
import { liveMessages } from './messages'
import type { LiveKey } from './messages'
import './live.css'

const EVERY = ['manual', '15', '60', '1440', '10080'] as const
const FORMATS = ['csv', 'tsv', 'xlsx', 'json', 'jsonl'] as const

export function ConnectorsPanel() {
  const { t, locale, formatTime } = usePack(liveMessages)
  const [items, setItems] = useState<Connector[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [said, setSaid] = useState('')
  const [runStates, setRunStates] = useState<Record<string, string>>({})
  const [deleting, setDeleting] = useState<Connector | null>(null)
  const [open, setOpen] = useState(false)

  const { status, lastContact } = useLive((change) => {
    if (change.kind === 'connector') {
      setItems((list) =>
        list?.map((item) =>
          item.id === change.id
            ? {
                ...item,
                enabled: change.enabled,
                last_status: change.last_status,
                last_error: change.last_error,
                last_run_id: change.last_run_id,
                last_checked_at: change.last_checked_at,
                next_due_at: change.next_due_at,
              }
            : item,
        ) ?? list,
      )
    } else if (change.connector_id) {
      setRunStates((states) => ({ ...states, [change.id]: change.state }))
    }
  })

  useEffect(() => {
    connectorsApi
      .list()
      .then((result) => setItems(result.connectors ?? []))
      .catch((error) => setLoadError(error instanceof ApiError ? error.message : t('live.failedLoad')))
    // Loaded once; the event stream keeps it current.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function replace(changed: Connector) {
    setItems((list) => list?.map((item) => (item.id === changed.id ? changed : item)) ?? [changed])
  }

  function describe(item: Connector): string {
    const time = item.last_checked_at ? formatTime(item.last_checked_at) : ''
    if (item.last_status === 'updated') return t('live.updated', { time })
    if (item.last_status === 'unchanged') return t('live.unchanged', { time })
    if (item.last_status === 'failed') return t('live.failed', { time, error: item.last_error ?? '' })
    return t('live.never')
  }

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const every = String(form.get('every'))
    const format = String(form.get('format'))
    setSaving(true)
    setFormError(null)
    try {
      const created = await connectorsApi.create({
        name: String(form.get('name')),
        url: String(form.get('url')),
        goal: String(form.get('goal')),
        format: format === 'auto' ? null : format,
        every_minutes: every === 'manual' ? null : Number(every),
        language: locale,
      })
      setItems((list) => [...(list ?? []), created])
      setOpen(false)
      setSaid(created.name)
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : t('live.failedLoad'))
    } finally {
      setSaving(false)
    }
  }

  async function refresh(item: Connector) {
    setBusy(item.id)
    try {
      const result = await connectorsApi.refresh(item.id, locale)
      replace(result.connector)
      setSaid(`${item.name}: ${describe(result.connector)}`)
    } catch (error) {
      setSaid(error instanceof ApiError ? error.message : t('live.failedLoad'))
    } finally {
      setBusy(null)
    }
  }

  async function toggle(item: Connector) {
    try {
      replace(await connectorsApi.update(item.id, { enabled: !item.enabled }, locale))
    } catch (error) {
      setSaid(error instanceof ApiError ? error.message : t('live.failedLoad'))
    }
  }

  async function remove(item: Connector) {
    try {
      await connectorsApi.remove(item.id)
      setItems((list) => list?.filter((entry) => entry.id !== item.id) ?? list)
    } catch (error) {
      setSaid(error instanceof ApiError ? error.message : t('live.failedLoad'))
    } finally {
      setDeleting(null)
    }
  }

  return (
    <section className="card" aria-labelledby="live-title">
      <div className="live-head">
        <h3 className="card__title" id="live-title">
          {t('live.title')}
        </h3>
        <LiveBadge status={status} lastContact={lastContact} />
      </div>
      <p className="field__help">{t('live.help')}</p>
      {/* The outcome of the last action, shown and announced. */}
      <p className={said ? 'statusline' : 'visually-hidden'} role="status" aria-live="polite" dir="auto">
        {said}
      </p>

      {loadError ? (
        <p className="statusline statusline--error" role="alert" dir="auto">
          {loadError}
        </p>
      ) : items === null ? (
        <div className="skeleton skeleton--line" />
      ) : items.length === 0 ? (
        <p className="panel__note">{t('live.empty')}</p>
      ) : (
        <ul className="live-list">
          {items.map((item) => (
            <li key={item.id} className="live-source">
              <span className="dataset__name" dir="auto">
                {item.name}
                {!item.enabled ? <span className="dataset__tag">{t('live.paused')}</span> : null}
              </span>
              <span className="live-source__url" dir="ltr">
                {item.url}
              </span>
              <span className="dataset__meta">
                {t(`live.every.${item.every_minutes ?? 'manual'}` as LiveKey)}
                {item.format ? ` · ${formatLabel(t, item.format)}` : ''}
              </span>
              <span className={item.last_status === 'failed' ? 'statusline statusline--error' : 'statusline'} dir="auto">
                {describe(item)}
                {item.last_status !== 'failed' && item.last_error ? ` ${item.last_error}` : ''}
                {item.last_run_id && runStates[item.last_run_id]
                  ? ` ${t('live.runState', { state: stateLabel(t, runStates[item.last_run_id]) })}`
                  : ''}
                {item.enabled && item.next_due_at ? ` ${t('live.next', { time: formatTime(item.next_due_at) })}` : ''}
              </span>
              <span className="live-source__actions">
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={busy === item.id}
                  aria-label={t('live.refreshAria', { name: item.name })}
                  onClick={() => void refresh(item)}
                >
                  {busy === item.id ? <span className="spinner" aria-hidden="true" /> : <Icon name="refresh" size={16} />}
                  {busy === item.id ? t('live.refreshing') : t('live.refresh')}
                </button>
                {item.last_run_id ? (
                  <a className="btn btn--ghost" href={routeHash({ tab: 'runs', runId: item.last_run_id })}>
                    {t('live.openRun')}
                  </a>
                ) : null}
                {item.every_minutes ? (
                  <button type="button" className="btn btn--ghost" onClick={() => void toggle(item)}>
                    {item.enabled ? t('live.pause') : t('live.resume')}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn--ghost"
                  aria-label={t('live.deleteAria', { name: item.name })}
                  onClick={() => setDeleting(item)}
                >
                  {t('live.delete')}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <details className="live-add" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary className="btn btn--ghost">
          <Icon name="plus" size={16} />
          {t('live.add')}
        </summary>
        <form className="live-form" onSubmit={(event) => void add(event)}>
          <div className="field">
            <label className="field__label" htmlFor="live-name">
              {t('live.name')}
            </label>
            <input id="live-name" name="name" className="field__input" required maxLength={100} dir="auto" />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="live-url">
              {t('live.url')}
            </label>
            <input
              id="live-url"
              name="url"
              type="url"
              className="field__input"
              required
              maxLength={2000}
              dir="ltr"
              placeholder="https://"
              aria-describedby="live-url-help"
            />
            <span className="field__help" id="live-url-help">
              {t('live.urlHelp')}
            </span>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="live-format">
              {t('live.format')}
            </label>
            <select id="live-format" name="format" className="field__select" defaultValue="auto">
              <option value="auto">{t('live.formatAuto')}</option>
              {FORMATS.map((format) => (
                <option key={format} value={format}>
                  {formatLabel(t, format)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="live-every">
              {t('live.every')}
            </label>
            <select id="live-every" name="every" className="field__select" defaultValue="manual">
              {EVERY.map((every) => (
                <option key={every} value={every}>
                  {t(`live.every.${every}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="field live-form__wide">
            <label className="field__label" htmlFor="live-goal">
              {t('live.goal')}
            </label>
            <input
              id="live-goal"
              name="goal"
              className="field__input"
              required
              maxLength={500}
              dir="auto"
              defaultValue={t('live.goalDefault')}
            />
          </div>
          {formError ? (
            <p className="statusline statusline--error live-form__wide" role="alert" dir="auto">
              {formError}
            </p>
          ) : null}
          <div className="live-form__wide">
            <button type="submit" className="btn btn--primary" disabled={saving}>
              {saving ? t('live.saving') : t('live.save')}
            </button>
          </div>
        </form>
      </details>

      {deleting ? (
        <ConfirmDialog
          title={t('live.deleteTitle')}
          message={t('live.deleteText')}
          confirmLabel={t('live.delete')}
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
    </section>
  )
}
