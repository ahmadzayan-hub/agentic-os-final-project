/** Views that load on demand (ADR 0028).
 *
 *  The session opens on the assistant, so the chat view and the shell
 *  ship in the first download; every other view and dialog is its own
 *  chunk, fetched the first time it is shown. Once the session is up,
 *  the chunks are fetched in idle time, so a later click is as quick as
 *  before and the service worker holds them for offline use. A reader
 *  who has asked to save data skips that prefetch. */
import { Component, lazy } from 'react'
import type { ReactNode } from 'react'
import { useI18n } from '../i18n'
import { Icon } from '../shared/components/Icon'

const loaders = {
  approvals: () => import('../features/approvals/ApprovalsView'),
  overview: () => import('../features/overview/OverviewView'),
  datasets: () => import('../features/datasets/DatasetsView'),
  runs: () => import('../features/runs/RunsView'),
  dashboard: () => import('../features/dashboard/DashboardView'),
  memory: () => import('../features/memory/MemoryView'),
  preferences: () => import('../features/preferences/PreferencesView'),
  activity: () => import('../features/activity/ActivityView'),
  palette: () => import('../features/commands/CommandPalette'),
  help: () => import('../features/commands/HelpDialog'),
  onboarding: () => import('../features/onboarding/Onboarding'),
  signIn: () => import('../features/auth/SignIn'),
}

export const ApprovalsView = lazy(() => loaders.approvals().then((m) => ({ default: m.ApprovalsView })))
export const OverviewView = lazy(() => loaders.overview().then((m) => ({ default: m.OverviewView })))
export const DatasetsView = lazy(() => loaders.datasets().then((m) => ({ default: m.DatasetsView })))
export const RunsView = lazy(() => loaders.runs().then((m) => ({ default: m.RunsView })))
export const DashboardView = lazy(() => loaders.dashboard().then((m) => ({ default: m.DashboardView })))
export const MemoryView = lazy(() => loaders.memory().then((m) => ({ default: m.MemoryView })))
export const PreferencesView = lazy(() =>
  loaders.preferences().then((m) => ({ default: m.PreferencesView })),
)
export const ActivityView = lazy(() => loaders.activity().then((m) => ({ default: m.ActivityView })))
export const CommandPalette = lazy(() =>
  loaders.palette().then((m) => ({ default: m.CommandPalette })),
)
export const HelpDialog = lazy(() => loaders.help().then((m) => ({ default: m.HelpDialog })))
export const Onboarding = lazy(() => loaders.onboarding().then((m) => ({ default: m.Onboarding })))
export const SignIn = lazy(() => loaders.signIn().then((m) => ({ default: m.SignIn })))

/** Fetch every view's chunk now. A failure is ignored: the view shows
 *  its own message if it is opened and still cannot load. */
export function prefetchViews(): Promise<void> {
  return Promise.all(Object.values(loaders).map((load) => load().catch(() => undefined))).then(
    () => undefined,
  )
}

/** True when the reader's browser asks pages to save data. */
export function savesData(): boolean {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection
  return connection?.saveData === true
}

/** Run the prefetch once the browser is idle; returns a cancel function. */
export function prefetchWhenIdle(): () => void {
  if (savesData()) return () => {}
  const idle = window.requestIdleCallback
  if (idle) {
    const handle = idle(() => void prefetchViews(), { timeout: 3000 })
    return () => window.cancelIdleCallback(handle)
  }
  const handle = window.setTimeout(() => void prefetchViews(), 1500)
  return () => window.clearTimeout(handle)
}

/** What the main area shows while a view's chunk is on its way. */
export function ViewLoading() {
  const { t } = useI18n()
  return (
    <div className="viewload" role="status" aria-label={t('app.loadingView')}>
      <div className="skeleton skeleton--title" />
      <div className="skeleton skeleton--line" />
      <div className="skeleton skeleton--line skeleton--short" />
    </div>
  )
}

function ViewFailed() {
  const { t } = useI18n()
  return (
    <div className="empty" role="alert" style={{ margin: 'auto' }}>
      <div className="empty__icon">
        <Icon name="alert" size={32} />
      </div>
      <p>{t('app.viewFailed')}</p>
      <p style={{ marginTop: 'var(--space-4)' }}>
        <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
          <Icon name="refresh" size={16} />
          {t('app.reload')}
        </button>
      </p>
    </div>
  )
}

interface ViewBoundaryProps {
  children: ReactNode
  /** Shown instead of the failure message; dialogs pass null. */
  fallback?: ReactNode
}

/** Catches a chunk that could not be fetched, usually because the
 *  reader is offline and never opened that view. React keeps a failed
 *  lazy import failed, so the way out is a reload, which says so. */
export class ViewBoundary extends Component<ViewBoundaryProps, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return this.props.fallback === undefined ? <ViewFailed /> : this.props.fallback
  }
}
