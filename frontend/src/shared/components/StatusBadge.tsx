import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n'
import type { ConnectionStatus } from '../types'

const LABELS: Record<ConnectionStatus, MessageKey> = {
  ready: 'status.ready',
  working: 'status.working',
  offline: 'status.offline',
  error: 'status.error',
  ended: 'status.ended',
}

/** Live session status shown in the header and announced to screen readers. */
export function StatusBadge({ status }: { status: ConnectionStatus }) {
  const { t } = useI18n()
  return (
    <span className={`badge badge--${status}`} role="status" aria-live="polite">
      <span className="badge__dot" aria-hidden="true" />
      {t(LABELS[status])}
    </span>
  )
}
