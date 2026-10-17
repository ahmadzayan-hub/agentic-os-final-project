/** Messages that ship with their view (ADR 0035).
 *
 *  The main dictionaries load with the shell. A view fetched on demand
 *  (ADR 0028) keeps its own strings in a pack beside it, so they arrive
 *  with its chunk instead of weighing on every first load. A pack holds
 *  both languages, and the types make the Arabic table name exactly the
 *  English one's keys, as the main dictionaries do. */
import { useCallback } from 'react'
import { interpolate, useI18n } from '.'
import type { Locale, MessageKey, Vars } from '.'

export type Pack<K extends string> = Readonly<Record<Locale, Readonly<Record<K, string>>>>

export function definePack<K extends string>(
  en: Record<K, string>,
  ar: Record<NoInfer<K>, string>,
): Pack<K> {
  return { en, ar }
}

/** `useI18n`, with `t` reading the pack first and the main dictionary
 *  for everything else. */
export function usePack<K extends string>(pack: Pack<K>) {
  const i18n = useI18n()
  const { locale, t: main } = i18n
  const t = useCallback(
    (key: K | MessageKey, vars?: Vars) =>
      Object.hasOwn(pack.en, key)
        ? interpolate(pack[locale][key as K] ?? pack.en[key as K], vars)
        : main(key as MessageKey, vars),
    [pack, locale, main],
  )
  return { ...i18n, t }
}
