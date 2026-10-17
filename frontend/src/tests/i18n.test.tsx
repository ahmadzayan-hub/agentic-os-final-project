import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ar, arPlurals } from '../i18n/ar'
import { en, enPlurals } from '../i18n/en'
import {
  applyLocale,
  currentLocale,
  localeFromPreference,
  storedLocale,
  translate,
  translatePlural,
  useI18n,
} from '../i18n'
import { usePack } from '../i18n/pack'
import { dashMessages } from '../features/dashboard/messages'
import { joinMessages, modelMessages } from '../features/runs/messages'
import { liveMessages } from '../features/live/messages'
import { StatusBadge } from '../shared/components/StatusBadge'

afterEach(() => {
  applyLocale('en')
  localStorage.clear()
})

describe('the dictionaries', () => {
  it('cover the same keys in both languages', () => {
    // The type system enforces this at compile time; this keeps it true
    // at runtime too, where a stray `as` cast could hide a gap.
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort())
    expect(Object.keys(arPlurals).sort()).toEqual(Object.keys(enPlurals).sort())
  })

  it('leave no Arabic string empty or identical to English by accident', () => {
    const untranslated = (Object.keys(en) as Array<keyof typeof en>).filter(
      (key) => ar[key].trim() === '' || (ar[key] === en[key] && /[a-z]{4,}/i.test(en[key])),
    )
    // Product names, file formats and file paths are the same in both
    // languages and are allowed; everything else must differ.
    expect(untranslated).toEqual(['brand.name', 'format.xlsx', 'format.json', 'format.jsonl'])
  })

  it('use the same placeholders in both languages', () => {
    const names = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort()
    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect(names(ar[key]), key).toEqual(names(en[key]))
    }
  })
})

describe('applyLocale', () => {
  it('stamps lang and dir on <html> and remembers the choice', () => {
    applyLocale('ar')
    expect(document.documentElement.lang).toBe('ar')
    expect(document.documentElement.dir).toBe('rtl')
    expect(currentLocale()).toBe('ar')
    expect(storedLocale()).toBe('ar')

    applyLocale('en')
    expect(document.documentElement.dir).toBe('ltr')
    expect(storedLocale()).toBe('en')
  })

  it('can apply a session language without recording it as a choice', () => {
    applyLocale('ar', false)
    expect(currentLocale()).toBe('ar')
    expect(storedLocale()).toBeNull()
  })
})

describe('translate', () => {
  it('reads the locale at call time and interpolates', () => {
    expect(translate('memory.updated', { date: '1 Jan' })).toBe('Updated 1 Jan')
    applyLocale('ar')
    expect(translate('memory.updated', { date: '1 Jan' })).toBe('حُدّث في 1 Jan')
  })

  it('leaves an unknown placeholder visible rather than dropping it', () => {
    expect(translate('memory.updated', {})).toBe('Updated {date}')
  })

  it('maps the spellings a person might type to a locale', () => {
    for (const value of ['Arabic', 'ar', 'العربية', 'عربي']) {
      expect(localeFromPreference(value)).toBe('ar')
    }
    for (const value of ['English', 'en', 'French', undefined, '']) {
      expect(localeFromPreference(value)).toBe('en')
    }
  })
})

describe('plurals', () => {
  it('pick the English form', () => {
    expect(translatePlural('runs.rows', 1)).toBe('1 data row')
    expect(translatePlural('runs.rows', 12)).toBe('12 data rows')
  })

  it('pick all six Arabic categories', () => {
    applyLocale('ar')
    expect(translatePlural('runs.rows', 0)).toBe('لا توجد صفوف بيانات')
    expect(translatePlural('runs.rows', 1)).toBe('صف بيانات واحد')
    expect(translatePlural('runs.rows', 2)).toBe('صفّا بيانات')
    expect(translatePlural('runs.rows', 3)).toBe('3 صفوف بيانات')
    expect(translatePlural('runs.rows', 11)).toBe('11 صف بيانات')
    expect(translatePlural('runs.rows', 100)).toBe('100 صف بيانات')
  })

  it('keep Western digits in Arabic, matching the English reports', () => {
    applyLocale('ar')
    expect(translatePlural('activity.messages', 25)).toContain('25')
    expect(translatePlural('activity.messages', 25)).not.toMatch(/[٠-٩]/)
  })
})

function Rich() {
  const { tx } = useI18n()
  return <p>{tx('composer.hintCommands', { ctrl: <kbd>Ctrl</kbd>, k: <kbd>K</kbd> })}</p>
}

describe('useI18n', () => {
  it('re-renders a component when the locale changes', () => {
    render(<StatusBadge status="ready" />)
    expect(screen.getByRole('status')).toHaveTextContent('Ready')
    // The locale lives outside React (on <html>); the store notifies
    // subscribers, and React flushes that inside act() as it would on
    // a real event.
    act(() => applyLocale('ar'))
    expect(screen.getByRole('status')).toHaveTextContent('جاهز')
  })

  it('places React nodes inside a translated sentence', () => {
    render(<Rich />)
    const paragraph = screen.getByText(/for commands/)
    expect(paragraph.querySelectorAll('kbd')).toHaveLength(2)
    expect(paragraph.textContent).toBe('Ctrl+K for commands')
  })

  it('formats times with Western digits in Arabic', () => {
    function Clock() {
      const { formatTime } = useI18n()
      return <time>{formatTime('2026-09-23T14:05:00Z')}</time>
    }
    applyLocale('ar')
    render(<Clock />)
    const shown = screen.getByText(/\d/).textContent ?? ''
    expect(shown).toMatch(/\d{1,2}:\d{2}/)
    expect(shown).not.toMatch(/[٠-٩]/)
  })
})

// A view's own strings (ADR 0035) are held to the main dictionaries'
// rules: the same keys and placeholders in both languages, none blank or
// left in English, and no key that the main dictionary also defines.
describe('message packs', () => {
  const packs = { dashMessages, joinMessages, modelMessages, liveMessages }
  const names = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort()

  for (const [name, pack] of Object.entries(packs)) {
    it(`${name} matches in both languages`, () => {
      const keys = Object.keys(pack.en) as Array<keyof typeof pack.en>
      expect(Object.keys(pack.ar).sort()).toEqual([...keys].sort())
      for (const key of keys) {
        const english = pack.en[key] as string
        const arabic = pack.ar[key] as string
        expect(names(arabic), key).toEqual(names(english))
        expect(arabic.trim(), key).not.toBe('')
        expect(arabic === english && /[a-z]{4,}/i.test(english), key).toBe(false)
        expect(Object.hasOwn(en, key), `${key} is also in the main dictionary`).toBe(false)
      }
    })
  }

  it('usePack reads its pack first and the main dictionary for the rest', () => {
    function Probe() {
      const { t } = usePack(modelMessages)
      return (
        <p>
          {t('models.used', { n: 72 })} | {t('status.ready')}
        </p>
      )
    }
    render(<Probe />)
    expect(screen.getByText(/Records used/).textContent).toBe('Records used: 72 | Ready')
    act(() => applyLocale('ar'))
    expect(screen.getByText(/السجلات/).textContent).toBe('السجلات المستخدمة: 72 | جاهز')
  })
})
