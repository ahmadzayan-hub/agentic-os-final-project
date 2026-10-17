import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MappingPanel, withRole } from '../features/datasets/MappingPanel'
import type { ColumnMapping, DatasetDetail } from '../shared/types'

const SUGGESTION: ColumnMapping = {
  roles: { order_date: 'date', region: 'dimension', amount: 'measure', notes: 'ignore' },
  measure: 'amount',
  dimension: 'region',
  date_order: 'auto',
  grain: 'auto',
}

const DETAIL: DatasetDetail = {
  dataset: {
    id: 'ds1',
    sha256: 'abcdef1234567890',
    name: 'shop.csv',
    byte_size: 420,
    created_at: '2026-10-16T09:00:00+00:00',
    source_format: 'csv',
    row_count: 12,
    column_count: 4,
    mapped: false,
    mapping_updated_at: null,
  },
  columns: [
    { name: 'order_date', type: 'date', filled: 12, cells: 12, numeric_share: 0, date_share: 1, distinct: 12,
      examples: ['15/11/2024'], ambiguous_order: false, suggested_role: 'date',
      reason: 'Reads as dates in 100% of filled cells.' },
    { name: 'region', type: 'text', filled: 12, cells: 12, numeric_share: 0, date_share: 0, distinct: 2,
      examples: ['North', 'South'], ambiguous_order: false, suggested_role: 'dimension',
      reason: 'Text with 2 distinct values.' },
    { name: 'amount', type: 'number', filled: 12, cells: 12, numeric_share: 1, date_share: 0, distinct: 12,
      examples: ['$1,200'], ambiguous_order: false, suggested_role: 'measure',
      reason: 'Numbers in 100% of filled cells.' },
    { name: 'notes', type: 'text', filled: 12, cells: 12, numeric_share: 0, date_share: 0, distinct: 12,
      examples: ['first order'], ambiguous_order: false, suggested_role: 'ignore',
      reason: 'Nearly every value is different, like names or notes.' },
  ],
  preview: [['15/11/2024', 'North', '$1,200', 'first order']],
  row_count: 12,
  profiled_rows: 12,
  mapping: null,
  suggestion: SUGGESTION,
}

type Reply = { status: number; body: unknown }

/** Answer requests in order; each records its method and body. */
function serve(replies: Reply[]) {
  const queue = [...replies]
  const fetchMock = vi.fn((_path: string, _init?: RequestInit) => {
    const reply = queue.shift() ?? { status: 500, body: { detail: 'unexpected' } }
    return Promise.resolve({
      ok: reply.status < 400,
      status: reply.status,
      json: () => Promise.resolve(reply.body),
    } as Response)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPanel(props: Partial<Parameters<typeof MappingPanel>[0]> = {}) {
  const handlers = { onClose: vi.fn(), onChanged: vi.fn(), onAnalyse: vi.fn() }
  render(<MappingPanel datasetId="ds1" focusOnOpen {...handlers} {...props} />)
  return handlers
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('withRole', () => {
  const order = ['order_date', 'region', 'amount', 'notes']

  it('keeps the measure and breakdown on columns that still have those roles', () => {
    const noMeasure = withRole(SUGGESTION, 'amount', 'ignore', order)
    expect(noMeasure.measure).toBeNull()
    const another = withRole(noMeasure, 'notes', 'measure', order)
    expect(another.measure).toBe('notes')
    const noBreakdown = withRole(SUGGESTION, 'region', 'ignore', order)
    expect(noBreakdown.dimension).toBeNull()
    expect(withRole(SUGGESTION, 'notes', 'dimension', order).dimension).toBe('region')
  })
})

describe('MappingPanel', () => {
  it('shows the first rows and the suggested role of each column, with its reason', async () => {
    serve([{ status: 200, body: DETAIL }])
    renderPanel()
    expect(await screen.findByRole('heading', { name: 'Columns of shop.csv' })).toHaveFocus()
    const preview = screen.getByRole('region', { name: 'First rows of shop.csv' })
    expect(within(preview).getByRole('columnheader', { name: 'amount' })).toBeInTheDocument()
    expect(within(preview).getByRole('cell', { name: '$1,200' })).toBeInTheDocument()
    const amount = screen.getByRole('combobox', { name: 'amount' })
    expect(amount).toHaveValue('measure')
    expect(amount).toHaveAccessibleDescription(/Numbers in 100% of filled cells/)
    expect(screen.getByRole('combobox', { name: 'Measure analysed' })).toHaveValue('amount')
    expect(screen.getByRole('combobox', { name: 'Breakdown' })).toHaveValue('region')
    expect(screen.getByText(/not saved yet\. Runs detect columns/)).toBeInTheDocument()
    expect(screen.queryByText('You have changes that are not saved yet.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse with automatic detection' })).toBeInTheDocument()
  })

  it('saves the draft and tells the list the dataset is mapped', async () => {
    const user = userEvent.setup()
    const saved = {
      ...DETAIL,
      dataset: { ...DETAIL.dataset, mapped: true, mapping_updated_at: '2026-10-16T10:00:00+00:00' },
      mapping: { ...SUGGESTION, dimension: null, version: 1 },
    }
    const fetchMock = serve([
      { status: 200, body: DETAIL },
      { status: 200, body: saved },
    ])
    const { onChanged } = renderPanel()
    await screen.findByRole('heading', { name: 'Columns of shop.csv' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Breakdown' }), '')
    expect(screen.getByText('You have changes that are not saved yet.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save mapping' }))
    const [path, init] = fetchMock.mock.calls[1]
    expect(path).toBe('/api/datasets/ds1/mapping?language=en')
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(String(init?.body))).toEqual({ ...SUGGESTION, dimension: null })
    expect(await screen.findByText('Mapping saved. Runs of this dataset now follow it.')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalledWith(saved.dataset)
    expect(screen.getByRole('button', { name: 'Use automatic detection' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse with this mapping' })).toBeInTheDocument()
  })

  it('shows a refusal as an error summary that links to each field', async () => {
    const user = userEvent.setup()
    serve([
      { status: 200, body: DETAIL },
      {
        status: 422,
        body: {
          detail: {
            message: 'The mapping was not saved: 2 problems to fix.',
            errors: [
              { field: 'roles', column: 'region', message: '“region” cannot be a measure: 0 of 12 filled cells are numbers.' },
              { field: 'measure', column: null, message: 'Choose which measure the analysis is about.' },
            ],
          },
        },
      },
    ])
    renderPanel()
    await screen.findByRole('heading', { name: 'Columns of shop.csv' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'region' }), 'measure')
    await user.click(screen.getByRole('button', { name: 'Save mapping' }))

    const summary = await screen.findByRole('alert')
    expect(summary).toHaveFocus()
    expect(within(summary).getByText('There is a problem')).toBeInTheDocument()
    const region = screen.getByRole('combobox', { name: 'region' })
    expect(region).toHaveAttribute('aria-invalid', 'true')
    expect(region).toHaveAccessibleDescription(/cannot be a measure/)
    expect(screen.getByRole('combobox', { name: 'Measure analysed' })).toHaveAttribute('aria-invalid', 'true')

    await user.click(within(summary).getByRole('link', { name: /cannot be a measure/ }))
    expect(region).toHaveFocus()
  })

  it('offers the date options only when a column is the date', async () => {
    const user = userEvent.setup()
    serve([{ status: 200, body: DETAIL }])
    renderPanel()
    await screen.findByRole('heading', { name: 'Columns of shop.csv' })
    expect(screen.getByRole('combobox', { name: 'Dates are written' })).toHaveValue('auto')
    await user.selectOptions(screen.getByRole('combobox', { name: 'order_date' }), 'ignore')
    expect(screen.queryByRole('combobox', { name: 'Dates are written' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Sum dates by' })).not.toBeInTheDocument()
  })

  it('says why it could not load, and tries again', async () => {
    const user = userEvent.setup()
    serve([
      { status: 404, body: { detail: 'Dataset not found.' } },
      { status: 200, body: DETAIL },
    ])
    renderPanel({ focusOnOpen: false })
    expect(await screen.findByText('Dataset not found.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Columns of shop.csv' })).toBeInTheDocument()
  })
})
