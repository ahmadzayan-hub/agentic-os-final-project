import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { Icon } from '../../shared/components/Icon'
import type { IconName } from '../../shared/components/Icon'
import type { SessionState } from '../../shared/types'
import { Composer } from './Composer'
import type { ComposerHandle } from './Composer'
import { MessageBubble } from './MessageBubble'

export interface Suggestion {
  label: MessageKey
  icon: IconName
  /** What goes into the composer — a sentence, in the reader's language. */
  insert: MessageKey
}

export const SUGGESTIONS: Suggestion[] = [
  { label: 'suggestion.analyse', icon: 'sparkle', insert: 'suggestion.analyse.insert' },
  { label: 'suggestion.remember', icon: 'memory', insert: 'suggestion.remember.insert' },
  { label: 'suggestion.explain', icon: 'activity', insert: 'suggestion.explain.insert' },
  { label: 'suggestion.help', icon: 'help', insert: 'suggestion.help.insert' },
]

function periodOf(hour: number): MessageKey {
  return hour < 12 ? 'greeting.morning' : hour < 18 ? 'greeting.afternoon' : 'greeting.evening'
}

interface ChatViewProps {
  session: SessionState
  sending: boolean
  failedText: string | null
  offline: boolean
  userName: string | null
  onSend: (text: string) => void
  onRetry: () => void
  onDismissFailed: () => void
  composerRef: React.RefObject<ComposerHandle | null>
}

export function ChatView({
  session,
  sending,
  failedText,
  offline,
  userName,
  onSend,
  onRetry,
  onDismissFailed,
  composerRef,
}: ChatViewProps) {
  const { t, tx } = useI18n()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [pinnedToBottom, setPinnedToBottom] = useState(true)
  const transcriptLength = session.transcript.length

  // Follow new messages only while the reader is already at the bottom, so
  // auto-scroll never fights manual scrolling through older messages.
  useEffect(() => {
    const container = scrollRef.current
    if (container && pinnedToBottom) {
      container.scrollTop = container.scrollHeight
    }
  }, [transcriptLength, sending, pinnedToBottom])

  function handleScroll() {
    const container = scrollRef.current
    if (!container) return
    const distance = container.scrollHeight - container.scrollTop - container.clientHeight
    setPinnedToBottom(distance < 48)
  }

  // A failed or in-flight first message must render the stream (with its
  // retry affordance), not the empty-state hero.
  const empty = transcriptLength === 0 && !failedText && !sending

  const period = t(periodOf(new Date().getHours()))
  const greeting = userName ? t('greeting.withName', { period, name: userName }) : period

  return (
    <section className="chat" aria-label={t('chat.aria')}>
      <div className="chat__scroll" ref={scrollRef} onScroll={handleScroll}>
        {empty ? (
          <div className="chat__empty">
            <div className="hero__orb" aria-hidden="true">
              <Icon name="sparkle" size={26} />
            </div>
            <h2 className="hero__greeting">{greeting}</h2>
            <p className="hero__question">{t('chat.question')}</p>
            <div className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion.label}
                  type="button"
                  className="suggestion"
                  onClick={() => composerRef.current?.insert(t(suggestion.insert))}
                >
                  <Icon name={suggestion.icon} size={16} />
                  {t(suggestion.label)}
                </button>
              ))}
            </div>
            <p className="hero__hint">
              <span dir="auto">{session.welcome}</span>{' '}
              {tx('chat.hint', {
                slash: <kbd>/</kbd>,
                shortcut: (
                  <>
                    <kbd>Ctrl</kbd>+<kbd>K</kbd>
                  </>
                ),
              })}
            </p>
          </div>
        ) : (
          <div className="chat__stream" aria-live="polite">
            {session.transcript.map((entry) => (
              <MessageBubble key={entry.id} entry={entry} agentName={session.agent_name} />
            ))}
            {sending ? (
              <div className="typing" role="status" aria-label={t('chat.typing')}>
                <span className="typing__dot" />
                <span className="typing__dot" />
                <span className="typing__dot" />
              </div>
            ) : null}
            {failedText ? (
              <div className="alertbar" role="alert">
                <Icon name="alert" size={16} />
                <span>{t('chat.failed')}</span>
                <button type="button" className="alertbar__retry" onClick={onRetry}>
                  {t('chat.retry')}
                </button>
                <button
                  type="button"
                  className="iconbtn"
                  style={{ width: 28, height: 28 }}
                  onClick={onDismissFailed}
                  aria-label={t('chat.dismiss')}
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
            ) : null}
            {session.ended ? (
              <div className="alertbar alertbar--info" role="status">
                <Icon name="power" size={16} />
                <span>{t('chat.ended')}</span>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {!pinnedToBottom && !empty ? (
        <button
          type="button"
          className="jump"
          onClick={() => {
            const container = scrollRef.current
            if (container) container.scrollTop = container.scrollHeight
            setPinnedToBottom(true)
          }}
        >
          <Icon name="arrowDown" size={14} />
          {t('chat.latest')}
        </button>
      ) : null}

      <Composer
        ref={composerRef}
        onSend={onSend}
        busy={sending}
        disabled={session.ended || offline}
      />
    </section>
  )
}
