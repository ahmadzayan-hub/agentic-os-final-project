import { useState } from 'react'
import { useI18n } from '../../i18n'
import { Icon } from '../../shared/components/Icon'
import type { TranscriptEntry } from '../../shared/types'

interface MessageBubbleProps {
  entry: TranscriptEntry
  agentName: string
}

export function MessageBubble({ entry, agentName }: MessageBubbleProps) {
  const { t, formatTime } = useI18n()
  const [copied, setCopied] = useState(false)
  const isAgent = entry.role === 'agent'

  async function copy() {
    try {
      await navigator.clipboard.writeText(entry.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard unavailable (permissions/insecure context) — leave silently.
    }
  }

  return (
    <article className={`msg msg--${entry.role}`} aria-label={isAgent ? t('msg.agent') : t('msg.you')}>
      {isAgent ? (
        <div className="msg__head">
          <span className="msg__avatar" aria-hidden="true">
            A
          </span>
          <span className="msg__author" dir="auto">
            {agentName}
          </span>
          <time dateTime={entry.time}>{formatTime(entry.time)}</time>
        </div>
      ) : null}
      {/* Each bubble orients by its own content: an English reply in an
          Arabic interface, or an Arabic question in an English one, reads
          in its own direction rather than the page's. */}
      <div className="msg__bubble" dir="auto">
        {entry.text}
      </div>
      <div className="msg__meta">
        {isAgent ? (
          <>
            <button type="button" className="msg__copy" onClick={copy}>
              <Icon name={copied ? 'check' : 'copy'} size={13} />
              {copied ? t('msg.copied') : t('msg.copy')}
            </button>
            {/* Honest about who understood: a model's phrasing is
                labelled as such, the way a report names its narrator. */}
            {entry.source === 'model' ? (
              <span className="msg__source">
                {t('msg.viaModel', { provider: entry.provider ?? 'model' })}
              </span>
            ) : null}
          </>
        ) : (
          <time dateTime={entry.time}>{formatTime(entry.time)}</time>
        )}
      </div>
    </article>
  )
}
