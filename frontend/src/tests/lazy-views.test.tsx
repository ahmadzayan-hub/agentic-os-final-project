import { act, render, screen } from '@testing-library/react'
import { Suspense } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  HelpDialog,
  prefetchViews,
  prefetchWhenIdle,
  ViewBoundary,
  ViewLoading,
} from '../app/lazyViews'
import { applyLocale } from '../i18n'

afterEach(() => {
  applyLocale('en')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function Broken(): never {
  throw new Error('chunk failed to load')
}

describe('views loaded on demand', () => {
  it('say they are loading, then show the view', async () => {
    render(
      <Suspense fallback={<ViewLoading />}>
        <HelpDialog commands={[]} onClose={() => {}} />
      </Suspense>,
    )
    expect(screen.getByRole('status', { name: 'Loading this view' })).toBeInTheDocument()
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Loading this view' })).not.toBeInTheDocument()
  })

  it('all resolve, so a prefetch leaves nothing to fail later', async () => {
    await expect(prefetchViews()).resolves.toBeUndefined()
  })
})

describe('a view that cannot load', () => {
  it('says so in the reader’s language and offers a reload', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    act(() => applyLocale('ar'))
    render(
      <ViewBoundary>
        <Broken />
      </ViewBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('تعذّر عرض هذه الصفحة')
    expect(screen.getByRole('button', { name: 'أعد تحميل الصفحة' })).toBeInTheDocument()
  })

  it('leaves the page as it was when it is a dialog', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(
      <ViewBoundary fallback={null}>
        <Broken />
      </ViewBoundary>,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('the idle prefetch', () => {
  it('waits for idle time', () => {
    const idle = vi.fn(() => 1)
    vi.stubGlobal('requestIdleCallback', idle)
    vi.stubGlobal('cancelIdleCallback', vi.fn())
    const cancel = prefetchWhenIdle()
    expect(idle).toHaveBeenCalledOnce()
    cancel()
    expect(window.cancelIdleCallback).toHaveBeenCalledWith(1)
  })

  it('is skipped for a reader who asked to save data', () => {
    const idle = vi.fn(() => 1)
    vi.stubGlobal('requestIdleCallback', idle)
    vi.stubGlobal('navigator', { ...navigator, connection: { saveData: true } })
    prefetchWhenIdle()()
    expect(idle).not.toHaveBeenCalled()
  })
})
