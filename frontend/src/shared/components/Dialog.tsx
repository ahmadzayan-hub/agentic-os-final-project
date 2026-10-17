import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface DialogProps {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
  labelledById?: string
  /** Long evidence surfaces start at their heading, before a scrollable table. */
  initialFocus?: 'panel'
}

/** Accessible modal dialog: focus is trapped inside, restored on close,
 *  and Escape or a scrim click dismisses it. */
export function Dialog({ title, onClose, children, wide, labelledById, initialFocus }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = labelledById ?? 'dialog-title'

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    if (!panel) return

    const focusables = panel.querySelectorAll<HTMLElement>(FOCUSABLE)
    if (initialFocus === 'panel') {
      panel.focus({ preventScroll: true })
      panel.scrollTop = 0
    } else { (focusables[0] ?? panel).focus() }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !panel) return
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus()
    }
  }, [onClose, initialFocus])

  return (
    <div
      className="dialog__scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={wide ? 'dialog dialog--wide' : 'dialog'}
        tabIndex={-1}
      >
        <h2 className="dialog__title" id={titleId}>
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}

