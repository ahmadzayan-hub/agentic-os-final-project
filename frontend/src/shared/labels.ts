/** Labels for values that arrive from the server as identifiers.
 *
 *  A run state, a memory category, a report type: the server sends the
 *  identifier and the screen names it in the reader's language. Anything
 *  outside the known set — a category somebody typed, a state a newer
 *  server added — is shown as-is rather than hidden, because an
 *  identifier the reader can see beats a blank they cannot explain. */
import { localeFromPreference } from '../i18n'
import type { MessageKey, Vars } from '../i18n'

type Translate = (key: MessageKey, vars?: Vars) => string

const TONES = new Set(['friendly', 'concise', 'formal'])
const STATES = new Set([
  'queued',
  'running',
  'awaiting_approval',
  'completed',
  'partially_completed',
  'failed',
  'cancelled',
  'pending',
  'succeeded',
  'skipped',
])
const CATEGORIES = new Set(['general', 'profile', 'work', 'projects', 'preferences'])
// The server names the causal section by its stage role, "experiment";
// the reader knows it as the causal question.
const TYPES: Record<string, string> = {
  descriptive: 'descriptive',
  diagnostic: 'diagnostic',
  experiment: 'causal',
  causal: 'causal',
  predictive: 'predictive',
  prescriptive: 'prescriptive',
}

export function toneLabel(t: Translate, tone: string): string {
  return TONES.has(tone) ? t(`tone.${tone}` as MessageKey) : tone
}

/** The agent's `language` preference as the reader should see it. A
 *  value nobody recognises (someone typed "French") is shown verbatim
 *  rather than silently mapped to English. */
export function languageLabel(t: Translate, value: unknown): string {
  const raw = String(value ?? '')
  const lowered = raw.trim().toLowerCase()
  if (lowered === 'english' || lowered === 'en') return t('language.en')
  if (localeFromPreference(lowered) === 'ar') return t('language.ar')
  return raw
}

export function stateLabel(t: Translate, state: string): string {
  return STATES.has(state) ? t(`state.${state}` as MessageKey) : state.replace(/_/g, ' ')
}

export function categoryLabel(t: Translate, category: string): string {
  if (CATEGORIES.has(category)) return t(`category.${category}` as MessageKey)
  return category.charAt(0).toUpperCase() + category.slice(1)
}

export function typeLabel(t: Translate, type: string): string {
  const known = TYPES[type]
  return known ? t(`type.${known}` as MessageKey) : type
}

/** The question a report section answers. The server's own wording is
 *  the fallback, so an unknown type still reads sensibly. */
export function questionLabel(t: Translate, type: string, fallback: string): string {
  const known = TYPES[type]
  return known ? t(`question.${known}` as MessageKey) : fallback
}
