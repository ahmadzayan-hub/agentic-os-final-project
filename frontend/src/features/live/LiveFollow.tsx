/** A dashboard over a live source's snapshot (ADR 0034): the stream's
 *  state, and a polite notice when a newer snapshot of the same source
 *  has been analysed. The page never swaps its figures by itself; the
 *  reader chooses to open the newer analysis. */
import { useState } from 'react'
import { usePack } from '../../i18n/pack'
import { useLive } from './live'
import { LiveBadge } from './LiveBadge'
import { liveMessages } from './messages'

const READY = new Set(['awaiting_approval', 'published'])

export function LiveFollow({ runId, connectorId, createdAt, onOpen }: {
  runId: string
  connectorId: string
  /** When this run was made: only a run made later is newer. */
  createdAt: string
  onOpen: (runId: string) => void
}) {
  const { t } = usePack(liveMessages)
  const [newer, setNewer] = useState<string | null>(null)
  const { status, lastContact } = useLive((change) => {
    if (
      change.kind === 'run' &&
      change.connector_id === connectorId &&
      change.id !== runId &&
      READY.has(change.state) &&
      change.created_at > createdAt
    ) {
      setNewer(change.id)
    }
  })
  return (
    <div className="live-follow">
      <LiveBadge status={status} lastContact={lastContact} />
      <div aria-live="polite">
        {newer ? (
          <p className="live-notice">
            <span>{t('live.newer')}</span>
            <button type="button" className="btn btn--ghost" onClick={() => onOpen(newer)}>
              {t('live.openNewer')}
            </button>
          </p>
        ) : null}
      </div>
    </div>
  )
}
