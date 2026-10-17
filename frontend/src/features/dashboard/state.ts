/** What a dashboard reader chose, kept in the address (ADR 0032).
 *
 *  `f.<column>` may repeat, one value each: the values of that column to
 *  keep. `from` and `to` bound the date; `lo`, `hi` and `hiop` bound the
 *  analysed measure (a bar of the histogram). `by` is the breakdown,
 *  `per=1` reads it per record, `vs` is the second measure, `sort`/`desc`
 *  order the records and `o` is the records page's offset. */
import type { TableField, TableFilter } from '../../shared/types'

export const PAGES = ['overview', 'breakdown', 'trend', 'distribution', 'relationship', 'records'] as const
export type Page = (typeof PAGES)[number]

export interface DashState {
  filters: Record<string, string[]>
  from: string | null
  to: string | null
  lo: number | null
  hi: number | null
  hiop: 'lt' | 'lte'
  by: string | null
  per: boolean
  vs: string | null
  sort: string | null
  desc: boolean
  offset: number
}

export const EMPTY: DashState = {
  filters: {}, from: null, to: null, lo: null, hi: null, hiop: 'lte',
  by: null, per: false, vs: null, sort: null, desc: false, offset: 0,
}

function finite(text: string | null): number | null {
  if (text === null || text.trim() === '') return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

export function readState(query: string): DashState {
  const params = new URLSearchParams(query)
  const filters: Record<string, string[]> = {}
  for (const [key, value] of params) {
    if (key.startsWith('f.') && key.length > 2) (filters[key.slice(2)] ??= []).push(value)
  }
  const offset = Number(params.get('o'))
  return {
    filters,
    from: params.get('from'),
    to: params.get('to'),
    lo: finite(params.get('lo')),
    hi: finite(params.get('hi')),
    hiop: params.get('hiop') === 'lt' ? 'lt' : 'lte',
    by: params.get('by'),
    per: params.get('per') === '1',
    vs: params.get('vs'),
    sort: params.get('sort'),
    desc: params.get('desc') === '1',
    offset: Number.isInteger(offset) && offset > 0 ? offset : 0,
  }
}

/** The address form of a state, in a stable order, without defaults. */
export function writeState(state: DashState): string {
  const params = new URLSearchParams()
  for (const column of Object.keys(state.filters).sort()) {
    for (const value of state.filters[column]) params.append(`f.${column}`, value)
  }
  if (state.from) params.set('from', state.from)
  if (state.to) params.set('to', state.to)
  if (state.lo !== null) params.set('lo', String(state.lo))
  if (state.hi !== null) {
    params.set('hi', String(state.hi))
    if (state.hiop === 'lt') params.set('hiop', 'lt')
  }
  if (state.by) params.set('by', state.by)
  if (state.per) params.set('per', '1')
  if (state.vs) params.set('vs', state.vs)
  if (state.sort) params.set('sort', state.sort)
  if (state.desc) params.set('desc', '1')
  if (state.offset) params.set('o', String(state.offset))
  return params.toString()
}

/** The filters every query on every page carries. */
export function toFilters(state: DashState, date: string | null, measure: string | null): TableFilter[] {
  const filters: TableFilter[] = Object.entries(state.filters)
    .filter(([, values]) => values.length)
    .map(([column, values]) => ({ column, op: 'in', values }))
  if (date && state.from) filters.push({ column: date, op: 'gte', value: state.from })
  if (date && state.to) filters.push({ column: date, op: 'lte', value: state.to })
  if (measure && state.lo !== null) filters.push({ column: measure, op: 'gte', value: state.lo })
  if (measure && state.hi !== null) filters.push({ column: measure, op: state.hiop, value: state.hi })
  return filters
}

/** How many filters are set, for the clear button and the page header. */
export function filterCount(state: DashState): number {
  return (
    Object.values(state.filters).filter((values) => values.length).length +
    (state.from || state.to ? 1 : 0) +
    (state.lo !== null || state.hi !== null ? 1 : 0)
  )
}

export interface Roles {
  measure: string | null
  breakdown: string | null
  date: string | null
  measures: string[]
  texts: TableField[]
}

/** The run's measure, breakdown and date, as the run itself chose them. */
export function rolesOf(fields: TableField[]): Roles {
  const measures = fields.filter((f) => f.type === 'number').map((f) => f.name)
  const texts = fields.filter((f) => f.type === 'text' && f.role !== 'date')
  const measure = fields.find((f) => f.role === 'analysed')?.name ?? measures[0] ?? null
  const breakdown =
    fields.find((f) => f.role === 'breakdown' && f.type === 'text')?.name ??
    texts.find((f) => f.values && f.values.length > 1)?.name ??
    null
  const date = fields.find((f) => f.role === 'date')?.name ?? null
  return { measure, breakdown, date, measures, texts }
}

/** The pages this table can fill. */
export function pagesFor(roles: Roles): Page[] {
  return PAGES.filter((page) => {
    if (page === 'breakdown') return roles.texts.length > 0 && roles.measure !== null
    if (page === 'trend') return roles.date !== null && roles.measure !== null
    if (page === 'distribution') return roles.measure !== null
    if (page === 'relationship') return roles.measures.length > 1
    return true
  })
}

/** A state that keeps the rows of one group: what drilling down does. */
export function drill(state: DashState, column: string, value: string, date: string | null): DashState {
  const next = { ...state, filters: { ...state.filters }, offset: 0 }
  if (column === date) {
    next.from = value
    next.to = value
  } else {
    next.filters[column] = [value]
  }
  return next
}
