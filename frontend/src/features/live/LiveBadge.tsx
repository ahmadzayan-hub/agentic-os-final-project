/** The event stream's state (ADR 0034): Live, Reconnecting or Offline,
 *  and, once it is not live, how old the figures on screen are. */
import { usePack } from '../../i18n/pack'
import type { LiveStatus } from './live'
import { liveMessages } from './messages'
import './live.css'

export function LiveBadge({ status, lastContact }: { status: LiveStatus; lastContact: number | null }) {
  const { t, formatTime } = usePack(liveMessages)
  const stale = status !== 'live' && lastContact !== null
  return (
    <span className={`live-badge live-badge--${status}`} role="status">
      <span className="live-badge__dot" aria-hidden="true" />
      {t(`live.${status}`)}
      {stale ? <span className="live-badge__since"> · {t('live.since', { time: formatTime(new Date(lastContact).toISOString()) })}</span> : null}
    </span>
  )
}
