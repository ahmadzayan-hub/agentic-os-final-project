/** Interface language: which one, which direction, and how to say things.
 *
 *  The choice lives on the <html> element (`lang` and `dir`), which is
 *  where CSS, the bidi algorithm, screen readers and Intl all read it
 *  from. An inline script in index.html stamps the saved choice before
 *  first paint, so an Arabic reader never sees a left-to-right flash;
 *  this module keeps React in step with that element, the same way
 *  useTheme keeps it in step with `data-theme`.
 *
 *  Two things are deliberately separate. The *interface* language is a
 *  per-browser choice stored locally. The *agent's* language is the
 *  session preference `language` that the server reads to phrase its
 *  own replies. Changing one changes the other, so a person picks once,
 *  but they are stored where each belongs. */
import { createElement, Fragment, useCallback, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { ar, arPlurals } from './ar'
import { en, enPlurals } from './en'
import type { MessageKey, PluralForms, PluralKey } from './en'

export type Locale = 'en' | 'ar'
export type Direction = 'ltr' | 'rtl'
export type Vars = Record<string, string | number>

export const LOCALE_KEY = 'aos-locale'

interface LocaleDefinition {
  messages: Record<MessageKey, string>
  plurals: Record<PluralKey, PluralForms>
  dir: Direction
  /** BCP 47 tag for Intl. `nu-latn` keeps digits Western in Arabic so a
   *  number on screen matches the same number in the English report. */
  tag: string
  /** The value the agent's `language` preference holds for this locale. */
  preference: string
}

const LOCALES: Record<Locale, LocaleDefinition> = {
  en: { messages: en, plurals: enPlurals, dir: 'ltr', tag: 'en', preference: 'English' },
  ar: { messages: ar, plurals: arPlurals, dir: 'rtl', tag: 'ar-u-nu-latn', preference: 'Arabic' },
}

const PLACEHOLDER = /\{(\w+)\}/g

export function isLocale(value: unknown): value is Locale {
  return value === 'en' || value === 'ar'
}

/** The agent's preference value → interface locale. Accepts what a
 *  person might type at `/set language …` in either language. */
export function localeFromPreference(value: unknown): Locale {
  const lowered = String(value ?? '').trim().toLowerCase()
  return ['arabic', 'ar', 'العربية', 'عربي', 'عربية', 'عربى'].includes(lowered) ? 'ar' : 'en'
}

export function preferenceFor(locale: Locale): string {
  return LOCALES[locale].preference
}

export function currentLocale(): Locale {
  return document.documentElement.lang === 'ar' ? 'ar' : 'en'
}

/** The locale a person chose in this browser, or null when they never did. */
export function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(LOCALE_KEY)
    return isLocale(value) ? value : null
  } catch {
    return null
  }
}

let listeners: Array<() => void> = []

function subscribe(listener: () => void) {
  listeners.push(listener)
  return () => {
    listeners = listeners.filter((item) => item !== listener)
  }
}

/** Stamp the locale on <html> and remember it. `persist: false` applies
 *  a session's language without recording it as this browser's choice. */
export function applyLocale(locale: Locale, persist = true) {
  const root = document.documentElement
  root.lang = locale
  root.dir = LOCALES[locale].dir
  if (persist) {
    try {
      localStorage.setItem(LOCALE_KEY, locale)
    } catch {
      /* private mode — the choice lasts this page only */
    }
  }
  listeners.forEach((listener) => listener())
}

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(PLACEHOLDER, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  )
}

/** Translate outside React (the store, the API client). Reads the
 *  current locale each call, so a message produced after a switch is in
 *  the new language. */
export function translate(key: MessageKey, vars?: Vars): string {
  const locale = currentLocale()
  const template = LOCALES[locale].messages[key] ?? en[key]
  return interpolate(template, vars)
}

function pluralForm(locale: Locale, key: PluralKey, n: number): string {
  const forms = LOCALES[locale].plurals[key] ?? enPlurals[key]
  const category = new Intl.PluralRules(LOCALES[locale].tag).select(n)
  return forms[category] ?? forms.other
}

export function translatePlural(key: PluralKey, n: number, vars?: Vars): string {
  return interpolate(pluralForm(currentLocale(), key, n), { n, ...vars })
}

/** A message with React nodes in place of `{name}` placeholders — for
 *  the few strings that carry a <kbd> or <code> in the middle of a
 *  sentence, where the word order differs between languages and so the
 *  markup cannot be split around a fixed English phrase. */
function rich(template: string, nodes: Record<string, ReactNode>): ReactNode {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of template.matchAll(PLACEHOLDER)) {
    const index = match.index ?? 0
    if (index > last) parts.push(template.slice(last, index))
    const name = match[1]
    parts.push(
      name in nodes
        ? createElement(Fragment, { key: `${name}-${index}` }, nodes[name])
        : match[0],
    )
    last = index + match[0].length
  }
  if (last < template.length) parts.push(template.slice(last))
  return createElement(Fragment, null, ...parts)
}

export function useI18n() {
  const locale = useSyncExternalStore(subscribe, currentLocale)
  const definition = LOCALES[locale]

  const t = useCallback(
    (key: MessageKey, vars?: Vars) => interpolate(definition.messages[key] ?? en[key], vars),
    [definition],
  )
  const tx = useCallback(
    (key: MessageKey, nodes: Record<string, ReactNode>) =>
      rich(definition.messages[key] ?? en[key], nodes),
    [definition],
  )
  const plural = useCallback(
    (key: PluralKey, n: number, vars?: Vars) =>
      interpolate(pluralForm(locale, key, n), { n, ...vars }),
    [locale],
  )
  const setLocale = useCallback((next: Locale) => applyLocale(next), [])

  const formatTime = useCallback(
    (iso: string, withSeconds = false) => {
      const date = new Date(iso)
      if (Number.isNaN(date.getTime())) return ''
      return new Intl.DateTimeFormat(definition.tag, {
        hour: '2-digit',
        minute: '2-digit',
        ...(withSeconds ? { second: '2-digit' } : {}),
      }).format(date)
    },
    [definition],
  )
  const formatDate = useCallback(
    (iso: string | null) => {
      if (!iso) return ''
      const date = new Date(iso)
      if (Number.isNaN(date.getTime())) return ''
      return new Intl.DateTimeFormat(definition.tag, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      }).format(date)
    },
    [definition],
  )
  const formatNumber = useCallback(
    (value: number, options?: Intl.NumberFormatOptions) =>
      new Intl.NumberFormat(definition.tag, options).format(value),
    [definition],
  )

  return {
    locale,
    dir: definition.dir,
    isRtl: definition.dir === 'rtl',
    t,
    tx,
    plural,
    setLocale,
    formatTime,
    formatDate,
    formatNumber,
  }
}

export type { MessageKey, PluralKey }
