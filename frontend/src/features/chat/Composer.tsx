import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { Icon } from '../../shared/components/Icon'

export interface ComposerHandle {
  insert: (text: string) => void
  focus: () => void
}

interface ComposerProps {
  onSend: (text: string) => void
  busy: boolean
  disabled?: boolean
  placeholder?: string
}

/** Multiline message input. Enter sends, Shift+Enter adds a line break.
 *  While a request is in flight the send action is disabled, which also
 *  prevents duplicate submissions. */
export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  { onSend, busy, disabled = false, placeholder },
  ref,
) {
  const { t, tx } = useI18n()
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useImperativeHandle(ref, () => ({
    insert(value: string) {
      setText(value)
      const textarea = textareaRef.current
      if (textarea) {
        textarea.focus()
        requestAnimationFrame(() => {
          textarea.setSelectionRange(value.length, value.length)
        })
      }
    },
    focus() {
      textareaRef.current?.focus()
    },
  }))

  function autosize() {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
  }

  function submit() {
    const value = text.trim()
    if (!value || busy || disabled) return
    onSend(value)
    setText('')
    requestAnimationFrame(autosize)
  }

  return (
    <div className="composer">
      <form
        className="composer__inner"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <label className="visually-hidden" htmlFor="composer-input">
          {t('composer.label')}
        </label>
        {/* dir="auto": a message is typed in whichever language the person
            thinks in, not necessarily the interface language. */}
        <textarea
          id="composer-input"
          ref={textareaRef}
          className="composer__input"
          rows={1}
          dir="auto"
          value={text}
          placeholder={disabled ? t('composer.ended') : (placeholder ?? t('composer.placeholder'))}
          disabled={disabled}
          onChange={(event) => {
            setText(event.target.value)
            autosize()
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
        />
        <button
          type="submit"
          className="composer__send"
          disabled={busy || disabled || !text.trim()}
          aria-label={busy ? t('composer.sending') : t('composer.send')}
        >
          {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="send" size={18} />}
        </button>
      </form>
      <p className="composer__hint">
        <span>
          {tx('composer.hintSend', { enter: <kbd>Enter</kbd>, shift: <kbd>Shift</kbd> })}
        </span>
        <span>{tx('composer.hintCommands', { ctrl: <kbd>Ctrl</kbd>, k: <kbd>K</kbd> })}</span>
      </p>
    </div>
  )
})
