/** Dashboard pages over one run's cleaned table (ADR 0032).
 *
 *  Every figure is asked of the server (ADR 0031): totals by group under
 *  the reader's filters, and the rows behind them. The filters, the page
 *  and every choice live in the address, so a filtered page survives a
 *  reload and can be shared with someone who can open the run. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n'
import { usePack } from '../../i18n/pack'
import { dashMessages, type DashKey } from './messages'
import { LiveFollow } from '../live/LiveFollow'
import { api, ApiError } from '../../shared/api'
import { Icon } from '../../shared/components/Icon'
import { stateLabel } from '../../shared/labels'
import type {
  GroupKey,
  QueryAnswer,
  QuerySpec,
  RecordsPage,
  RecordsSpec,
  RunDetail,
  RunSummary,
  TableField,
  TableFilter,
} from '../../shared/types'
import type { Route } from '../../app/routing'
import { routeHash } from '../../app/routing'
import { Bars, Figure, Histogram, Line, Scatter } from './charts'
import type { Point } from './charts'
import { drill, EMPTY, filterCount, pagesFor, readState, rolesOf, toFilters, writeState } from './state'
import type { DashState, Page, Roles } from './state'
import './dashboard.css'

const READY_STATES = ['awaiting_approval', 'completed', 'partially_completed']
const PAGE_SIZE = 25
const SAMPLE = 500

interface DashboardViewProps {
  runId: string | null
  page: string | null
  query: string
  onNavigate: (route: Route) => void
  onOpenRun: (id: string) => void
}

export function DashboardView({ runId, page, query, onNavigate, onOpenRun }: DashboardViewProps) {
  if (!runId) return <RunPicker onPick={(id) => onNavigate({ tab: 'dashboard', runId: id })} />
  return (
    <Dashboard key={runId} runId={runId} page={page} query={query} onNavigate={onNavigate} onOpenRun={onOpenRun} />
  )
}

function RunPicker({ onPick }: { onPick: (id: string) => void }) {
  const { t } = usePack(dashMessages)
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  useEffect(() => {
    let cancelled = false
    api
      .listRuns()
      .then((result) => !cancelled && setRuns(result.runs.filter((run) => READY_STATES.includes(run.state))))
      .catch(() => !cancelled && setRuns([]))
    return () => {
      cancelled = true
    }
  }, [])
  return (
    <section className="panel" aria-labelledby="dash-title">
      <div className="panel__inner panel__inner--wide">
        <div className="panel__header">
          <div>
            <h2 className="panel__title" id="dash-title">{t('dash.title')}</h2>
            <p className="panel__desc">{t('dash.pick')}</p>
          </div>
        </div>
        <div className="card">
          {runs === null ? (
            <div role="status" aria-label={t('dash.loading')} className="skeleton skeleton--line" />
          ) : runs.length === 0 ? (
            <p className="card__empty">{t('dash.none')}</p>
          ) : (
            <ul className="controls__list">
              {runs.map((run) => (
                <li key={run.id}>
                  <button type="button" className="controlrow" onClick={() => onPick(run.id)}>
                    <Icon name="dashboard" size={17} />
                    <span>
                      <span className="controlrow__label" dir="auto">{run.goal}</span>
                      <span className="controlrow__help">
                        <span dir="auto">{run.dataset_name}</span> · {stateLabel(t, run.state)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}

/** Answers kept for this session, so a page revisited is instant. */
const answers = new Map<string, unknown>()

function useAnswer<T>(key: string | null, load: () => Promise<T>) {
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string | null }>({
    key: null, data: null, error: null,
  })
  useEffect(() => {
    if (key === null) return
    if (answers.has(key)) {
      setState({ key, data: answers.get(key) as T, error: null })
      return
    }
    let cancelled = false
    setState((previous) => ({ ...previous, key, error: null }))
    load()
      .then((data) => {
        answers.set(key, data)
        if (!cancelled) setState({ key, data, error: null })
      })
      .catch((error) => {
        if (!cancelled) setState({ key, data: null, error: error instanceof ApiError ? error.message : String(error) })
      })
    return () => {
      cancelled = true
    }
    // `load` is rebuilt each render; the key says what it fetches.
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  const current = state.key === key
  return { data: current ? state.data : null, error: current ? state.error : null, loading: key !== null && (!current || (!state.data && !state.error)) }
}

function useQuery(runId: string, spec: QuerySpec | null) {
  const { locale } = useI18n()
  const key = spec ? `q:${runId}:${locale}:${JSON.stringify(spec)}` : null
  return useAnswer<QueryAnswer>(key, () => api.queryTable(runId, spec!, locale))
}

function useRecords(runId: string, spec: RecordsSpec | null) {
  const { locale } = useI18n()
  const key = spec ? `r:${runId}:${locale}:${JSON.stringify(spec)}` : null
  return useAnswer<RecordsPage>(key, () => api.tableRecords(runId, spec!, locale))
}

function keyText(key: GroupKey): string {
  if (key === null) return ''
  if (Array.isArray(key)) return `${key[0]} – ${key[1]}`
  return String(key)
}

interface PageProps {
  runId: string
  roles: Roles
  state: DashState
  filters: TableFilter[]
  setState: (next: DashState, page?: Page) => void
}

function Dashboard({ runId, page, query, onNavigate, onOpenRun }: {
  runId: string
  page: string | null
  query: string
  onNavigate: (route: Route) => void
  onOpenRun: (id: string) => void
}) {
  const { t, locale, formatNumber } = usePack(dashMessages)
  const state = useMemo(() => readState(query), [query])
  const fields = useAnswer<{ fields: TableField[]; records: number }>(`f:${runId}:${locale}`, () =>
    api.tableFields(runId, locale),
  )
  const run = useAnswer<RunDetail>(`run:${runId}`, () => api.getRun(runId))
  const roles = useMemo(() => (fields.data ? rolesOf(fields.data.fields) : null), [fields.data])
  const pages = roles ? pagesFor(roles) : []
  const current: Page = pages.includes(page as Page) ? (page as Page) : 'overview'
  const filters = useMemo(() => (roles ? toFilters(state, roles.date, roles.measure) : []), [state, roles])
  const coverage = useQuery(runId, roles ? { measures: [{ agg: 'count' }], filters, limit: 1 } : null)

  const setState = useCallback(
    (next: DashState, nextPage?: Page) => {
      onNavigate({ tab: 'dashboard', runId, page: nextPage ?? current, query: writeState(next) || undefined })
    },
    [onNavigate, runId, current],
  )

  if (fields.error) {
    return (
      <section className="panel" aria-labelledby="dash-title">
        <div className="panel__inner panel__inner--wide">
          <h2 className="panel__title" id="dash-title">{t('dash.title')}</h2>
          <p role="alert" className="statusline statusline--error" dir="auto">{fields.error}</p>
          <p>
            <button type="button" className="btn btn--ghost" onClick={() => onNavigate({ tab: 'dashboard' })}>
              {t('dash.other')}
            </button>
          </p>
        </div>
      </section>
    )
  }
  if (!fields.data || !roles) {
    return (
      <section className="panel" aria-label={t('dash.title')}>
        <div className="panel__inner panel__inner--wide">
          <div role="status" aria-label={t('dash.loading')} className="card">
            <div className="skeleton skeleton--title" />
            <div className="skeleton skeleton--line" />
          </div>
        </div>
      </section>
    )
  }

  const matched = coverage.data?.matched_records
  const props: PageProps = { runId, roles, state, filters, setState }
  return (
    <section className="panel" aria-labelledby="dash-title">
      <div className="panel__inner panel__inner--wide">
        <div className="panel__header">
          <div>
            <p className="eyebrow">{t('dash.title')}</p>
            <h2 className="panel__title" id="dash-title" dir="auto">{run.data?.goal ?? runId}</h2>
            {run.data ? <p className="panel__desc" dir="auto">{run.data.dataset_name}</p> : null}
          </div>
          <div className="dash-actions">
            <button type="button" className="btn btn--ghost" onClick={() => onOpenRun(runId)}>
              {t('dash.openRun')}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => onNavigate({ tab: 'dashboard' })}>
              {t('dash.other')}
            </button>
          </div>
        </div>
        {run.data?.connector_id ? (
          <LiveFollow
            runId={runId}
            connectorId={run.data.connector_id}
            createdAt={run.data.created_at}
            onOpen={(id) => onNavigate({ tab: 'dashboard', runId: id, page: current, query: writeState(state) || undefined })}
          />
        ) : null}

        <nav className="dash-pages" aria-label={t('dash.pages')}>
          <ul>
            {pages.map((name) => (
              <li key={name}>
                <a
                  href={routeHash({ tab: 'dashboard', runId, page: name, query: writeState({ ...state, offset: 0 }) || undefined })}
                  aria-current={current === name ? 'page' : undefined}
                  className="dash-pages__link"
                >
                  {t(`dash.page.${name}` as DashKey)}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <FilterBar fields={fields.data.fields} roles={roles} state={state} setState={setState} />
        <p className="dash-coverage" role="status" aria-live="polite">
          {matched === undefined
            ? t('dash.counting')
            : t('dash.coverage', { matched: formatNumber(matched), total: formatNumber(fields.data.records) })}
        </p>

        <div className="dash-page">
          <h3 className="visually-hidden">{t(`dash.page.${current}` as DashKey)}</h3>
          {current === 'overview' ? <OverviewPage {...props} /> : null}
          {current === 'breakdown' ? <BreakdownPage {...props} /> : null}
          {current === 'trend' ? <TrendPage {...props} /> : null}
          {current === 'distribution' ? <DistributionPage {...props} /> : null}
          {current === 'relationship' ? <RelationshipPage {...props} /> : null}
          {current === 'records' ? <RecordsPageView {...props} /> : null}
        </div>
      </div>
    </section>
  )
}

function FilterBar({ fields, roles, state, setState }: {
  fields: TableField[]
  roles: Roles
  state: DashState
  setState: (next: DashState) => void
}) {
  const { t, formatNumber } = usePack(dashMessages)
  const listed = roles.texts.filter((field) => field.values && field.values.length > 1)
  const periods = fields.find((field) => field.name === roles.date)?.values?.filter(Boolean) ?? []
  const count = filterCount(state)

  function toggle(column: string, value: string, on: boolean) {
    const values = new Set(state.filters[column] ?? [])
    if (on) values.add(value)
    else values.delete(value)
    const filters = { ...state.filters, [column]: [...values] }
    if (!filters[column].length) delete filters[column]
    setState({ ...state, filters, offset: 0 })
  }

  return (
    <section className="card dash-filters" aria-labelledby="dash-filters-title">
      <div className="dash-filters__head">
        <h3 className="card__title" id="dash-filters-title">{t('dash.filters')}</h3>
        {count ? (
          <button type="button" className="btn btn--subtle" onClick={() => setState({ ...EMPTY, by: state.by, per: state.per, vs: state.vs })}>
            {t('dash.clear', { n: formatNumber(count) })}
          </button>
        ) : null}
      </div>
      <div className="dash-filters__grid">
        {roles.date && periods.length > 1 ? (
          <div className="dash-range">
            <div className="field">
              <label className="field__label" htmlFor="dash-from">{t('dash.from')}</label>
              <select id="dash-from" className="field__select" value={state.from ?? ''}
                onChange={(event) => setState({ ...state, from: event.target.value || null, offset: 0 })}>
                <option value="">{t('dash.start')}</option>
                {periods.map((period) => <option key={period} value={period}>{period}</option>)}
              </select>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="dash-to">{t('dash.to')}</label>
              <select id="dash-to" className="field__select" value={state.to ?? ''}
                onChange={(event) => setState({ ...state, to: event.target.value || null, offset: 0 })}>
                <option value="">{t('dash.end')}</option>
                {periods.map((period) => <option key={period} value={period}>{period}</option>)}
              </select>
            </div>
          </div>
        ) : null}
        {listed.map((field) => {
          const chosen = state.filters[field.name] ?? []
          return (
            <details className="dash-filter" key={field.name}>
              <summary dir="auto">
                {field.name}: {chosen.length ? chosen.map((v) => v || t('dash.blank')).join(', ') : t('dash.all')}
              </summary>
              <fieldset className="dash-filter__values">
                <legend className="visually-hidden">{field.name}</legend>
                {field.values!.map((value) => (
                  <label key={value} className="dash-filter__value">
                    <input type="checkbox" checked={chosen.includes(value)}
                      onChange={(event) => toggle(field.name, value, event.target.checked)} />
                    <span dir="auto">{value || t('dash.blank')}</span>
                  </label>
                ))}
              </fieldset>
            </details>
          )
        })}
        {roles.measure && (state.lo !== null || state.hi !== null) ? (
          <p className="dash-filter__range" dir="auto">
            {t('dash.measureRange', {
              measure: roles.measure,
              from: state.lo === null ? '…' : formatNumber(state.lo),
              to: state.hi === null ? '…' : formatNumber(state.hi),
            })}
          </p>
        ) : null}
      </div>
    </section>
  )
}

function Problem({ message }: { message: string | null }) {
  return message ? <p role="alert" className="statusline statusline--error" dir="auto">{message}</p> : null
}

function Loading() {
  const { t } = usePack(dashMessages)
  return <div role="status" aria-label={t('dash.loading')} className="skeleton skeleton--line" />
}

/** A group table: label, values, records, and the way to its rows. */
function GroupTable({ head, rows, onDrill }: {
  head: string[]
  rows: Array<{ label: string; cells: string[]; drill?: () => void }>
  onDrill?: boolean
}) {
  const { t } = usePack(dashMessages)
  return (
    <table className="datatable">
      <thead>
        <tr>
          {head.map((name) => <th key={name} scope="col" dir="auto">{name}</th>)}
          {onDrill ? <th scope="col"><span className="visually-hidden">{t('dash.rowsBehind')}</span></th> : null}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.label}-${index}`}>
            <th scope="row" dir="auto">{row.label || t('dash.blank')}</th>
            {row.cells.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
            {onDrill ? (
              <td>
                {row.drill ? (
                  <button type="button" className="btn btn--subtle dash-drill" onClick={row.drill}
                    aria-label={t('dash.showRecordsFor', { group: row.label || t('dash.blank') })}>
                    {t('dash.showRecords')}
                  </button>
                ) : null}
              </td>
            ) : null}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function OverviewPage({ runId, roles, state, filters, setState }: PageProps) {
  const { t, formatNumber } = usePack(dashMessages)
  const m = roles.measure!
  const totals = useQuery(runId, {
    measures: [{ agg: 'count' }, { agg: 'sum', column: m }, { agg: 'mean', column: m }], filters, limit: 1,
  })
  const top = useQuery(runId, roles.breakdown ? {
    group_by: [roles.breakdown], measures: [{ agg: 'sum', column: m }, { agg: 'count' }], filters,
    sort: { by: `sum:${m}`, desc: true }, limit: 10,
  } : null)
  const trend = useQuery(runId, roles.date ? {
    group_by: [roles.date], measures: [{ agg: 'sum', column: m }, { agg: 'count' }], filters, limit: 1000,
  } : null)
  const values = totals.data?.groups[0]?.values ?? [0, null, null]
  const total = values[1]
  const leader = top.data?.groups[0]
  const trendPoints: Point[] = (trend.data?.groups ?? []).map((g) => ({ label: keyText(g.keys[0]), value: g.values[0] }))
  const topPoints: Point[] = (top.data?.groups ?? []).map((g) => ({ label: keyText(g.keys[0]), value: g.values[0] }))
  const number = (value: number | null | undefined) => (value === null || value === undefined ? '—' : formatNumber(value, { maximumFractionDigits: 2 }))
  return (
    <>
      <Problem message={totals.error ?? top.error ?? trend.error} />
      <div className="kpis dash-kpis">
        <div className="kpi"><span className="kpi__label">{t('dash.kpi.records')}</span><span className="kpi__value">{number(values[0])}</span></div>
        <div className="kpi"><span className="kpi__label" dir="auto">{t('dash.kpi.total', { measure: m })}</span><span className="kpi__value">{number(total)}</span></div>
        <div className="kpi"><span className="kpi__label" dir="auto">{t('dash.kpi.perRecord', { measure: m })}</span><span className="kpi__value">{number(values[2])}</span></div>
        {leader && roles.breakdown ? (
          <div className="kpi">
            <span className="kpi__label" dir="auto">{t('dash.kpi.largest', { breakdown: roles.breakdown })}</span>
            <span className="kpi__value" dir="auto">{keyText(leader.keys[0]) || t('dash.blank')}</span>
            <span className="kpi__sub">
              {total ? t('dash.kpi.share', { share: formatNumber((leader.values[0] ?? 0) / total, { style: 'percent', maximumFractionDigits: 1 }) }) : null}
            </span>
          </div>
        ) : null}
      </div>
      <div className="dash-grid">
        {roles.date ? (
          <div className="card">
            {trend.loading ? <Loading /> : (
              <Figure
                title={t('dash.chart.trend', { measure: m, date: roles.date })}
                chart={<Line points={trendPoints} label={t('dash.alt.trend', { measure: m, n: formatNumber(trendPoints.length) })} />}
                table={<GroupTable head={[roles.date, t('dash.col.total'), t('dash.col.records')]} onDrill
                  rows={(trend.data?.groups ?? []).map((g) => ({
                    label: keyText(g.keys[0]), cells: [number(g.values[0]), number(g.records)],
                    drill: () => setState(drill(state, roles.date!, keyText(g.keys[0]), roles.date), 'records'),
                  }))} />}
              />
            )}
          </div>
        ) : null}
        {roles.breakdown ? (
          <div className="card">
            {top.loading ? <Loading /> : (
              <Figure
                title={t('dash.chart.top', { measure: m, breakdown: roles.breakdown })}
                chart={<Bars items={topPoints} label={t('dash.alt.bars', { measure: m, breakdown: roles.breakdown, n: formatNumber(topPoints.length) })} />}
                table={<GroupTable head={[roles.breakdown, t('dash.col.total'), t('dash.col.records')]} onDrill
                  rows={(top.data?.groups ?? []).map((g) => ({
                    label: keyText(g.keys[0]), cells: [number(g.values[0]), number(g.records)],
                    drill: () => setState(drill(state, roles.breakdown!, keyText(g.keys[0]), roles.date), 'records'),
                  }))} />}
              />
            )}
          </div>
        ) : null}
      </div>
    </>
  )
}

function BreakdownPage({ runId, roles, state, filters, setState }: PageProps) {
  const { t, formatNumber } = usePack(dashMessages)
  const m = roles.measure!
  const by = roles.texts.some((f) => f.name === state.by) ? state.by! : roles.breakdown ?? roles.texts[0].name
  const key = state.per ? `mean:${m}` : `sum:${m}`
  const answer = useQuery(runId, {
    group_by: [by], measures: [{ agg: 'sum', column: m }, { agg: 'mean', column: m }, { agg: 'count' }],
    filters, sort: { by: key, desc: true }, limit: 50,
  })
  const groups = answer.data?.groups ?? []
  const points: Point[] = groups.map((g) => ({ label: keyText(g.keys[0]), value: g.values[state.per ? 1 : 0] }))
  const number = (value: number | null) => (value === null ? '—' : formatNumber(value, { maximumFractionDigits: 2 }))
  return (
    <div className="card">
      <div className="dash-controls">
        <div className="field">
          <label className="field__label" htmlFor="dash-by">{t('dash.by')}</label>
          <select id="dash-by" className="field__select" dir="auto" value={by}
            onChange={(event) => setState({ ...state, by: event.target.value })}>
            {roles.texts.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}
          </select>
        </div>
        <div className="field">
          <span className="field__label" id="dash-per-label">{t('dash.read')}</span>
          <div className="segmented" role="group" aria-labelledby="dash-per-label">
            <button type="button" className="segmented__option" aria-pressed={!state.per} onClick={() => setState({ ...state, per: false })}>{t('dash.totals')}</button>
            <button type="button" className="segmented__option" aria-pressed={state.per} onClick={() => setState({ ...state, per: true })}>{t('dash.perRecord')}</button>
          </div>
        </div>
      </div>
      <Problem message={answer.error} />
      {answer.loading ? <Loading /> : (
        <Figure
          open
          title={t(state.per ? 'dash.chart.byPer' : 'dash.chart.by', { measure: m, breakdown: by })}
          chart={<Bars items={points} label={t('dash.alt.bars', { measure: m, breakdown: by, n: formatNumber(points.length) })} />}
          table={<GroupTable head={[by, t('dash.col.total'), t('dash.col.perRecord'), t('dash.col.records')]} onDrill
            rows={groups.map((g) => ({
              label: keyText(g.keys[0]), cells: [number(g.values[0]), number(g.values[1]), number(g.records)],
              drill: () => setState(drill(state, by, keyText(g.keys[0]), roles.date), 'records'),
            }))} />}
        />
      )}
      {answer.data?.truncated ? (
        <p className="field__help">{t('dash.truncated', { shown: formatNumber(groups.length), total: formatNumber(answer.data.group_count) })}</p>
      ) : null}
    </div>
  )
}

function TrendPage({ runId, roles, state, filters, setState }: PageProps) {
  const { t, formatNumber } = usePack(dashMessages)
  const m = roles.measure!
  const date = roles.date!
  const answer = useQuery(runId, {
    group_by: [date], measures: [{ agg: 'sum', column: m }, { agg: 'mean', column: m }, { agg: 'count' }], filters, limit: 1000,
  })
  const groups = answer.data?.groups ?? []
  const number = (value: number | null) => (value === null ? '—' : formatNumber(value, { maximumFractionDigits: 2 }))
  const table = (
    <GroupTable head={[date, t('dash.col.total'), t('dash.col.perRecord'), t('dash.col.records')]} onDrill
      rows={groups.map((g) => ({
        label: keyText(g.keys[0]), cells: [number(g.values[0]), number(g.values[1]), number(g.records)],
        drill: () => setState(drill(state, date, keyText(g.keys[0]), date), 'records'),
      }))} />
  )
  return (
    <>
      <Problem message={answer.error} />
      {answer.loading ? <Loading /> : (
        <div className="dash-grid">
          <div className="card">
            <Figure title={t('dash.chart.trend', { measure: m, date })}
              chart={<Line points={groups.map((g) => ({ label: keyText(g.keys[0]), value: g.values[0] }))}
                label={t('dash.alt.trend', { measure: m, n: formatNumber(groups.length) })} />}
              table={table} />
          </div>
          <div className="card">
            <Figure open title={t('dash.chart.trendPer', { measure: m, date })}
              chart={<Line points={groups.map((g) => ({ label: keyText(g.keys[0]), value: g.values[1] }))}
                label={t('dash.alt.trendPer', { measure: m, n: formatNumber(groups.length) })} />}
              table={table} />
          </div>
        </div>
      )}
    </>
  )
}

function DistributionPage({ runId, roles, state, filters, setState }: PageProps) {
  const { t, formatNumber } = usePack(dashMessages)
  const m = roles.measure!
  const answer = useQuery(runId, { group_by: [{ column: m, bins: 12 }], measures: [{ agg: 'count' }], filters, limit: 50 })
  const bins = (answer.data?.groups ?? [])
    .filter((g) => Array.isArray(g.keys[0]))
    .map((g, index, all) => {
      const [from, to] = g.keys[0] as [number, number]
      return { from, to, count: g.records, last: index === all.length - 1 }
    })
  const empty = (answer.data?.groups ?? []).find((g) => g.keys[0] === null)
  return (
    <div className="card">
      <Problem message={answer.error} />
      {answer.loading ? <Loading /> : (
        <Figure open
          title={t('dash.chart.distribution', { measure: m })}
          chart={<Histogram bins={bins} label={t('dash.alt.distribution', { measure: m, n: formatNumber(bins.length) })} />}
          table={<GroupTable head={[t('dash.col.range'), t('dash.col.records')]} onDrill
            rows={bins.map((bin) => ({
              label: `${formatNumber(bin.from)} – ${formatNumber(bin.to)}`, cells: [formatNumber(bin.count)],
              drill: () => setState({ ...state, lo: bin.from, hi: bin.to, hiop: bin.last ? 'lte' : 'lt', offset: 0 }, 'records'),
            }))} />}
        />
      )}
      {empty ? <p className="field__help">{t('dash.noValue', { n: formatNumber(empty.records), measure: m })}</p> : null}
    </div>
  )
}

function RelationshipPage({ runId, roles, state, filters, setState }: PageProps) {
  const { t, formatNumber } = usePack(dashMessages)
  const m = roles.measure!
  const others = roles.measures.filter((name) => name !== m)
  const vs = others.includes(state.vs ?? '') ? state.vs! : others[0]
  const sample = useRecords(runId, { filters, sample: SAMPLE })
  const points = useMemo(() => {
    if (!sample.data) return []
    const xi = sample.data.columns.indexOf(vs)
    const yi = sample.data.columns.indexOf(m)
    return sample.data.rows
      .map((row) => ({ x: row[xi], y: row[yi] }))
      .filter((p): p is { x: number; y: number } => typeof p.x === 'number' && typeof p.y === 'number')
  }, [sample.data, vs, m])
  return (
    <div className="card">
      <div className="field">
        <label className="field__label" htmlFor="dash-vs">{t('dash.against')}</label>
        <select id="dash-vs" className="field__select" dir="auto" value={vs}
          onChange={(event) => setState({ ...state, vs: event.target.value })}>
          {others.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </div>
      <Problem message={sample.error} />
      {sample.loading ? <Loading /> : (
        <Figure
          title={t('dash.chart.relationship', { measure: m, other: vs })}
          chart={<Scatter points={points} label={t('dash.alt.relationship', { measure: m, other: vs, n: formatNumber(points.length) })} />}
          table={<GroupTable head={[vs, m]}
            rows={points.slice(0, 100).map((p) => ({ label: formatNumber(p.x), cells: [formatNumber(p.y)] }))} />}
        />
      )}
      {sample.data ? (
        <p className="field__help">
          {sample.data.sampled
            ? t('dash.sampled', { n: formatNumber(points.length), total: formatNumber(sample.data.total) })
            : t('dash.allPoints', { n: formatNumber(points.length) })}
        </p>
      ) : null}
    </div>
  )
}

function RecordsPageView({ runId, state, filters, setState }: PageProps) {
  const { t, formatNumber } = usePack(dashMessages)
  const page = useRecords(runId, {
    filters, offset: state.offset, limit: PAGE_SIZE,
    ...(state.sort ? { sort: { by: state.sort, desc: state.desc } } : {}),
  })
  const data = page.data
  const cell = (value: string | number | null) =>
    value === null ? '' : typeof value === 'number' ? formatNumber(value, { maximumFractionDigits: 4 }) : value
  return (
    <div className="card">
      {data ? (
        <div className="dash-controls">
          <div className="field">
            <label className="field__label" htmlFor="dash-sort">{t('dash.sort')}</label>
            <select id="dash-sort" className="field__select" dir="auto" value={state.sort ?? ''}
              onChange={(event) => setState({ ...state, sort: event.target.value || null, offset: 0 })}>
              <option value="">{t('dash.sortNone')}</option>
              {data.columns.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          {state.sort ? (
            <div className="field">
              <span className="field__label" id="dash-dir-label">{t('dash.direction')}</span>
              <div className="segmented" role="group" aria-labelledby="dash-dir-label">
                <button type="button" className="segmented__option" aria-pressed={!state.desc} onClick={() => setState({ ...state, desc: false, offset: 0 })}>{t('dash.ascending')}</button>
                <button type="button" className="segmented__option" aria-pressed={state.desc} onClick={() => setState({ ...state, desc: true, offset: 0 })}>{t('dash.descending')}</button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
      <Problem message={page.error} />
      {page.loading || !data ? <Loading /> : (
        <>
          <p className="field__help">
            {data.total
              ? t('dash.rowsShown', {
                  from: formatNumber(state.offset + 1),
                  to: formatNumber(Math.min(state.offset + PAGE_SIZE, data.total)),
                  total: formatNumber(data.total),
                })
              : t('dash.noRows')}
          </p>
          <div className="evidence__table" role="region" aria-label={t('dash.page.records')} tabIndex={0}>
            <table className="datatable">
              <thead>
                <tr>{data.columns.map((name) => <th key={name} scope="col" dir="auto">{name}</th>)}</tr>
              </thead>
              <tbody>
                {data.rows.map((row, index) => (
                  <tr key={state.offset + index}>
                    {row.map((value, column) => <td key={column} dir="auto">{cell(value)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="dash-controls">
            <button type="button" className="btn btn--ghost" disabled={state.offset === 0}
              onClick={() => setState({ ...state, offset: Math.max(0, state.offset - PAGE_SIZE) })}>
              {t('dash.previous')}
            </button>
            <button type="button" className="btn btn--ghost" disabled={state.offset + PAGE_SIZE >= data.total}
              onClick={() => setState({ ...state, offset: state.offset + PAGE_SIZE })}>
              {t('dash.next')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
