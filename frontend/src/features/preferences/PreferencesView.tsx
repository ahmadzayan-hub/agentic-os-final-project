import { useState } from 'react'
import { useMotion } from '../../app/useMotion'
import { useTheme } from '../../app/useTheme'
import type { ThemeChoice } from '../../app/useTheme'
import type { OperationOutcome } from '../../app/store'
import { useI18n } from '../../i18n'
import type { Locale, MessageKey } from '../../i18n'
import { toneLabel } from '../../shared/labels'
import type { PreferenceValue } from '../../shared/types'

const TONES = ['friendly', 'concise', 'formal'] as const
const THEMES: Array<{ id: ThemeChoice; label: MessageKey }> = [
  { id: 'dark', label: 'theme.dark' },
  { id: 'light', label: 'theme.light' },
  { id: 'system', label: 'theme.system' },
]
// Each language is named in itself, so the option a reader is looking
// for is legible whatever the interface currently says.
const LANGUAGES: Array<{ id: Locale; name: string }> = [
  { id: 'en', name: 'English' },
  { id: 'ar', name: 'العربية' },
]

interface PreferencesViewProps {
  preferences: Record<string, PreferenceValue>
  disabled: boolean
  locale: Locale
  onSet: (key: string, value: string) => Promise<OperationOutcome>
  onSetLanguage: (locale: Locale) => Promise<OperationOutcome>
}

export function PreferencesView({
  preferences,
  disabled,
  locale,
  onSet,
  onSetLanguage,
}: PreferencesViewProps) {
  const { t, tx } = useI18n()
  const { theme, setTheme } = useTheme()
  const { reducedMotion, setReducedMotion } = useMotion()
  const [statusMessage, setStatusMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [nameDraft, setNameDraft] = useState(String(preferences.user_name ?? ''))

  const tone = String(preferences.tone ?? 'friendly')
  const saveHistory = preferences.save_history !== false

  async function apply(key: string, value: string) {
    setBusyKey(key)
    const outcome = await onSet(key, value)
    setStatusMessage({ ok: outcome.ok, text: outcome.message })
    setBusyKey(null)
  }

  async function applyLanguage(next: Locale) {
    if (next === locale) return
    setBusyKey('language')
    const outcome = await onSetLanguage(next)
    setStatusMessage(outcome.message ? { ok: outcome.ok, text: outcome.message } : null)
    setBusyKey(null)
  }

  return (
    <section className="panel" aria-label={t('prefs.aria')}>
      <div className="panel__inner panel__inner--split">
        <div className="panel__column">
          <div className="panel__header">
            <div>
              <h2 className="panel__title">{t('prefs.title')}</h2>
              <p className="panel__desc">{tx('prefs.desc', { code: <code>config.json</code> })}</p>
            </div>
          </div>

          <div className="card">
            <div className="field">
              <span className="field__label" id="tone-label">
                {t('prefs.tone')}
              </span>
              <span className="field__help" id="tone-help">
                {t('prefs.toneHelp')}
              </span>
              <div
                className="segmented"
                role="group"
                aria-labelledby="tone-label"
                aria-describedby="tone-help"
              >
                {TONES.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className="segmented__option"
                    aria-pressed={tone === option}
                    disabled={busyKey !== null || disabled}
                    onClick={() => void apply('tone', option)}
                  >
                    {toneLabel(t, option)}
                  </button>
                ))}
              </div>
            </div>

            <form
              className="field"
              onSubmit={(event) => {
                event.preventDefault()
                const value = nameDraft.trim()
                if (value) void apply('user_name', value)
              }}
            >
              <label className="field__label" htmlFor="pref-name">
                {t('prefs.name')}
              </label>
              <span className="field__help">{t('prefs.nameHelp')}</span>
              <div className="field__row">
                <input
                  id="pref-name"
                  className="field__input"
                  type="text"
                  dir="auto"
                  placeholder={t('prefs.namePlaceholder')}
                  value={nameDraft}
                  maxLength={200}
                  onChange={(event) => setNameDraft(event.target.value)}
                  disabled={busyKey !== null || disabled}
                />
                <button
                  type="submit"
                  className="btn btn--ghost"
                  disabled={busyKey !== null || disabled || !nameDraft.trim()}
                >
                  {t('common.save')}
                </button>
              </div>
            </form>

            <div className="field">
              <span className="field__label" id="language-label">
                {t('prefs.language')}
              </span>
              <span className="field__help" id="language-help">
                {t('prefs.languageHelp')}
              </span>
              <div
                className="segmented"
                role="group"
                aria-labelledby="language-label"
                aria-describedby="language-help"
              >
                {LANGUAGES.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="segmented__option"
                    lang={option.id}
                    aria-pressed={locale === option.id}
                    disabled={busyKey !== null || disabled}
                    onClick={() => void applyLanguage(option.id)}
                  >
                    {option.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="field">
              <div className="switchrow">
                <div>
                  <span className="field__label" id="history-label">
                    {t('prefs.history')}
                  </span>
                  <p className="field__help">{t('prefs.historyHelp')}</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={saveHistory}
                  aria-labelledby="history-label"
                  className="switch"
                  disabled={busyKey !== null || disabled}
                  onClick={() => void apply('save_history', saveHistory ? 'false' : 'true')}
                >
                  <span className="switch__thumb" />
                </button>
              </div>
            </div>
          </div>

          <p
            className={`statusline ${
              statusMessage ? (statusMessage.ok ? 'statusline--success' : 'statusline--error') : ''
            }`}
            role="status"
            aria-live="polite"
            dir="auto"
          >
            {busyKey ? t('prefs.saving') : (statusMessage?.text ?? '')}
          </p>
        </div>

        <div className="panel__column panel__column--side">
          <div className="card">
            <h3 className="card__title">{t('prefs.interface')}</h3>
            <p className="panel__desc">{t('prefs.interfaceDesc')}</p>

            <div className="field">
              <span className="field__label" id="theme-label">
                {t('prefs.theme')}
              </span>
              <div className="segmented" role="group" aria-labelledby="theme-label">
                {THEMES.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="segmented__option"
                    aria-pressed={theme === option.id}
                    onClick={() => setTheme(option.id)}
                  >
                    {t(option.label)}
                  </button>
                ))}
              </div>
            </div>

            <div className="field">
              <div className="switchrow">
                <div>
                  <span className="field__label" id="motion-label">
                    {t('prefs.motion')}
                  </span>
                  <p className="field__help">{t('prefs.motionHelp')}</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={reducedMotion}
                  aria-labelledby="motion-label"
                  className="switch"
                  onClick={() => setReducedMotion(!reducedMotion)}
                >
                  <span className="switch__thumb" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
