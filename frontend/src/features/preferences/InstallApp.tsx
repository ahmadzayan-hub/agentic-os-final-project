import { useState } from 'react'
import { useI18n } from '../../i18n'
import { Icon } from '../../shared/components/Icon'
import { clearInstallPrompt, useInstall } from '../../app/installStore'

export function InstallApp() {
  const { t } = useI18n()
  const { prompt, installed } = useInstall()
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  async function install() {
    if (!prompt || busy) return
    setBusy(true); setFailed(false)
    try { await prompt.prompt(); await prompt.userChoice }
    catch { setFailed(true) }
    finally { clearInstallPrompt(); setBusy(false) }
  }
  return <section className="card install-card"><h3 className="card__title"><Icon name="download" size={18} />{t('install.title')}</h3><p>{t('install.desc')}</p>
    {installed ? <p className="assurance-strip">{t('install.installed')}</p> : <><ul><li>{t('install.windows')}</li><li>{t('install.android')}</li><li>{t('install.ios')}</li></ul>{prompt ? <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void install()}>{t('install.button')}</button> : null}</>}
    {failed ? <p role="status">{t('install.failed')}</p> : null}
    <p className="card__meta">{t('install.connection')}</p>
  </section>
}
