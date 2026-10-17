import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DatasetsView } from '../features/datasets/DatasetsView'
import { OverviewView } from '../features/overview/OverviewView'

const USAGE = {
  runs_today: { used: 3, limit: 200, remaining: 197 },
  datasets: { used: 1, limit: 20, remaining: 19 },
  dataset_bytes: { used: 48_250, limit: 50_000_000, remaining: 49_951_750 },
  not_tracked: [],
}

const DETAIL = {
  id: 'r2',
  goal: 'Why did revenue change?',
  dataset_name: 'sample sales dataset',
  state: 'completed',
  report_language: 'ar',
  reports: [
    { type: 'descriptive', question: '', title: '', headline: 'ارتفعت الإيرادات', content: '' },
    { type: 'diagnostic', question: '', title: '', headline: '', content: '' },
  ],
}

/** Answer each API path with its own body; anything else is a 404. */
function serve(bodies: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      const body = bodies[path]
      return Promise.resolve({
        ok: body !== undefined,
        status: body !== undefined ? 200 : 404,
        json: () => Promise.resolve(body ?? { detail: 'Not found.' }),
      } as Response)
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('OverviewView', () => {
  it('offers the sample data and an upload before anything is analysed', async () => {
    const user = userEvent.setup()
    serve({ '/api/runs': { runs: [] }, '/api/usage': USAGE })
    const onStart = vi.fn()
    render(<OverviewView onOpenRun={vi.fn()} onStart={onStart} />)

    expect(await screen.findByText('Nothing analysed yet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try the sample data' }))
    expect(onStart).toHaveBeenLastCalledWith(null)
    await user.click(screen.getByRole('button', { name: 'Add a dataset' }))
    expect(onStart).toHaveBeenLastCalledWith({ kind: 'upload' })
  })

  it('shows the figures, the latest headlines in their own language, and the approval queue', async () => {
    const user = userEvent.setup()
    serve({
      '/api/runs': {
        runs: [
          {
            id: 'r1',
            goal: 'Publish the Q4 review',
            dataset_name: 'q4.csv',
            state: 'awaiting_approval',
            created_at: '2026-10-15T09:00:00+00:00',
            updated_at: '2026-10-15T09:05:00+00:00',
          },
          {
            id: 'r2',
            goal: 'Why did revenue change?',
            dataset_name: 'sample sales dataset',
            state: 'completed',
            created_at: '2026-10-16T09:00:00+00:00',
            updated_at: '2026-10-16T09:05:00+00:00',
          },
        ],
      },
      '/api/runs/r2': DETAIL,
      '/api/usage': USAGE,
    })
    const onOpenRun = vi.fn()
    render(<OverviewView onOpenRun={onOpenRun} onStart={vi.fn()} />)

    const headline = await screen.findByText('ارتفعت الإيرادات')
    // The report's language, not the interface's, so it is read correctly.
    expect(headline).toHaveAttribute('lang', 'ar')
    expect(headline).toHaveAttribute('dir', 'rtl')
    // A report with no headline is left out rather than shown blank.
    expect(screen.queryByText('Diagnostic')).not.toBeInTheDocument()

    const figures = screen.getByText('Waiting for approval').closest('.kpi') as HTMLElement
    expect(within(figures).getByText('1')).toBeInTheDocument()
    expect(figures).toHaveClass('kpi--attention')
    expect(screen.getByText('of 200')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Publish the Q4 review.*Review/ }))
    expect(onOpenRun).toHaveBeenCalledWith('r1')
  })

  it('says so and offers a retry when the runs cannot be read', async () => {
    serve({ '/api/usage': USAGE })
    render(<OverviewView onOpenRun={vi.fn()} onStart={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('DatasetsView', () => {
  it('explains where datasets come from when there are none', async () => {
    serve({ '/api/datasets': { datasets: [] }, '/api/usage': USAGE })
    render(<DatasetsView onAnalyse={vi.fn()} />)
    expect(await screen.findByText('No datasets yet')).toBeInTheDocument()
  })

  it('analyses a stored dataset by reference', async () => {
    const user = userEvent.setup()
    const dataset = {
      id: 'ds1',
      sha256: '1a2b3c4d5e6f',
      name: 'quarterly-sales.csv',
      byte_size: 48_250,
      created_at: '2026-10-16T09:00:00+00:00',
    }
    serve({ '/api/datasets': { datasets: [dataset] }, '/api/usage': USAGE })
    const onAnalyse = vi.fn()
    render(<DatasetsView onAnalyse={onAnalyse} />)

    expect(await screen.findByText('48.3 kB')).toBeInTheDocument()
    expect(screen.getByText('fingerprint 1a2b3c4d')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Analyse quarterly-sales.csv' }))
    expect(onAnalyse).toHaveBeenCalledWith(dataset)
  })

  it('adds a file through the API and lists it with its format and rows', async () => {
    const user = userEvent.setup()
    const stored = {
      id: 'ds2',
      sha256: 'abcdef1234',
      name: 'book.xlsx',
      byte_size: 900,
      created_at: '2026-10-16T09:00:00+00:00',
      source_format: 'xlsx',
      row_count: 4,
      column_count: 3,
    }
    let listed: unknown[] = []
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (path.startsWith('/api/datasets?') && init?.method === 'POST') {
        listed = [stored]
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () =>
            Promise.resolve({
              dataset: stored,
              created: true,
              columns: ['team', 'quarter', 'sales'],
              preview: [],
              warnings: ['Read the sheet “Sales”, the first of 2.'],
              sheets: ['Sales', 'Notes'],
            }),
        } as Response)
      }
      // The live sources panel (ADR 0034): none saved, and no event stream.
      if (path === '/api/events') return Promise.resolve({ ok: false, status: 503 } as Response)
      const body =
        path === '/api/connectors'
          ? { connectors: [] }
          : path === '/api/datasets'
          ? { datasets: listed }
          : path.startsWith('/api/datasets/ds2')
            ? {
                dataset: stored,
                columns: [],
                preview: [],
                row_count: 4,
                profiled_rows: 4,
                mapping: null,
                suggestion: { roles: {}, measure: null, dimension: null, date_order: 'auto', grain: 'auto' },
              }
            : USAGE
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { container } = render(<DatasetsView onAnalyse={vi.fn()} />)
    expect(await screen.findByText('No datasets yet')).toBeInTheDocument()

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['PK'], 'book.xlsx'))

    expect(await screen.findByText('Added book.xlsx: 4 data rows.')).toBeInTheDocument()
    expect(screen.getByText('Read the sheet “Sales”, the first of 2.')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Analyse book.xlsx' })).toBeInTheDocument()
    expect(screen.getByText(/^Excel ·/)).toBeInTheDocument()
    // A new upload opens its columns, without taking focus from the status.
    const heading = await screen.findByRole('heading', { name: 'Columns of book.xlsx' })
    expect(heading).not.toHaveFocus()
  })
})
