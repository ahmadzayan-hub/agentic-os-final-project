import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import type { CommandInfo } from '../../shared/types'

interface CommandPaletteProps {
  commands: CommandInfo[]
  onPick: (command: CommandInfo) => void
  onClose: () => void
}

/** Searchable command palette (opened with Ctrl/Cmd+K). Picking a command
 *  inserts its usage into the composer so nobody has to memorize syntax. */
export function CommandPalette({ commands, onPick, onClose }: CommandPaletteProps) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = 'palette-listbox'

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return commands
    return commands.filter(
      (command) =>
        command.command.toLowerCase().includes(needle) ||
        command.description.toLowerCase().includes(needle),
    )
  }, [commands, query])

  useEffect(() => {
    // Full modal semantics: focus moves in on open and is restored to the
    // opener on close; Tab is contained (the input is the only stop).
    const previouslyFocused = document.activeElement as HTMLElement | null
    inputRef.current?.focus()
    return () => {
      previouslyFocused?.focus()
    }
  }, [])

  useEffect(() => {
    setActiveIndex(0)
  }, [query])

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') {
      onClose()
    } else if (event.key === 'Tab') {
      event.preventDefault()
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((index) => Math.min(index + 1, filtered.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter' && filtered[activeIndex]) {
      event.preventDefault()
      onPick(filtered[activeIndex])
    }
  }

  return (
    <div
      className="palette__scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label={t('palette.aria')}>
        <input
          ref={inputRef}
          className="palette__input"
          type="text"
          role="combobox"
          dir="auto"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={filtered[activeIndex] ? `palette-option-${activeIndex}` : undefined}
          placeholder={t('palette.placeholder')}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
        />
        {filtered.length === 0 ? (
          <p className="palette__empty">{t('palette.empty', { query })}</p>
        ) : (
          <ul className="palette__list" role="listbox" id={listId} aria-label={t('palette.list')}>
            {filtered.map((command, index) => (
              <li
                key={command.command}
                id={`palette-option-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                className="palette__item"
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => onPick(command)}
              >
                <span className="palette__cmd" dir="ltr">
                  {command.usage}
                </span>
                <span className="palette__desc" dir="auto">
                  {command.description}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
