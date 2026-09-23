import { useState } from 'react'
import { useI18n } from '../../i18n'
import { Icon } from '../../shared/components/Icon'
import type { AuthConfig } from '../../shared/types'

interface SignInProps {
  config: AuthConfig
  onSignedIn: (token: string) => void
}

/** Sign-in against the deployment's managed identity provider.
 *
 *  Credentials go straight from the browser to the provider's own
 *  endpoint (Supabase Auth) using its publishable key; this application
 *  never receives, stores, or proxies a password. It only keeps the
 *  returned access token to authorize API calls. */
export function SignIn({ config, onSignedIn }: SignInProps) {
  const { t, locale, setLocale } = useI18n()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const canUseProvider = config.flows.length > 0
  const otherLocale = locale === 'en' ? 'ar' : 'en'

  async function providerRequest(path: string, body: unknown) {
    const response = await fetch(`${config.provider_url}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: config.publishable_key,
        Authorization: `Bearer ${config.publishable_key}`,
      },
      body: JSON.stringify(body),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      const message =
        payload && typeof payload === 'object' && payload !== null
          ? ((payload as Record<string, unknown>).error_description ??
             (payload as Record<string, unknown>).msg ??
             (payload as Record<string, unknown>).message)
          : null
      throw new Error(typeof message === 'string' ? message : t('signin.failed'))
    }
    return payload as Record<string, unknown> | null
  }

  async function signInWithPassword(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const payload = await providerRequest('/auth/v1/token?grant_type=password', {
        email: email.trim(),
        password,
      })
      const token = payload?.access_token
      if (typeof token !== 'string' || !token) {
        throw new Error(t('signin.noToken'))
      }
      setPassword('')
      onSignedIn(token)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('signin.failed'))
    } finally {
      setBusy(false)
    }
  }

  async function sendMagicLink() {
    if (!email.trim()) {
      setError(t('signin.enterEmail'))
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await providerRequest('/auth/v1/otp', { email: email.trim() })
      setNotice(t('signin.checkEmail', { email: email.trim() }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('signin.linkFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="signin" aria-label={t('signin.aria')}>
      <div className="signin__card">
        <div className="signin__top">
          <span className="brand__mark signin__mark" aria-hidden="true">
            A
          </span>
          {/* No session exists yet, so this switches the interface only;
              the agent learns the language when the session is created. */}
          <button
            type="button"
            className="langbtn"
            aria-label={t('language.switch')}
            onClick={() => setLocale(otherLocale)}
          >
            <Icon name="globe" size={16} />
            <span lang={otherLocale}>{t('language.other')}</span>
          </button>
        </div>
        <h1 className="signin__title">{t('signin.title')}</h1>
        <p className="signin__desc">{t('signin.desc')}</p>

        {canUseProvider ? (
          <form onSubmit={signInWithPassword}>
            <div className="field">
              <label className="field__label" htmlFor="signin-email">
                {t('signin.email')}
              </label>
              <input
                id="signin-email"
                className="field__input"
                type="email"
                dir="ltr"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={busy}
                required
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="signin-password">
                {t('signin.password')}
              </label>
              <input
                id="signin-password"
                className="field__input"
                type="password"
                dir="ltr"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={busy}
              />
            </div>
            <div className="signin__actions">
              <button type="submit" className="btn btn--primary" disabled={busy || !email.trim()}>
                {busy ? <span className="spinner" aria-hidden="true" /> : null}
                {t('signin.submit')}
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => void sendMagicLink()}
                disabled={busy}
              >
                {t('signin.magic')}
              </button>
            </div>
          </form>
        ) : (
          <p className="signin__warning" role="status">
            <Icon name="alert" size={16} />
            {t('signin.noProvider')}
          </p>
        )}

        <p
          className={`statusline ${error ? 'statusline--error' : notice ? 'statusline--success' : ''}`}
          role="status"
          aria-live="polite"
          dir="auto"
        >
          {error ?? notice ?? ''}
        </p>
      </div>
    </main>
  )
}
