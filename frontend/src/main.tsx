import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { StoreProvider } from './app/store'
import { initializeInstall } from './app/installStore'
// Design system v2 (ADR 0023): the faces are bundled with the app, Latin
// subsets only, so they are cached offline and never fetched from a third
// party. Arabic text uses the system stack set in tokens.css.
import '@fontsource/fira-sans/latin-400.css'
import '@fontsource/fira-sans/latin-500.css'
import '@fontsource/fira-sans/latin-600.css'
import '@fontsource/fira-code/latin-400.css'
import '@fontsource/fira-code/latin-500.css'
import './shared/styles/tokens.css'
import './shared/styles/base.css'
import './shared/styles/app.css'
import './shared/styles/workspace.css'

initializeInstall()
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </StrictMode>,
)

// Installable PWA: register the service worker in production builds only,
// so development and tests always see live code.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* offline caching is progressive enhancement — the app works without it */
    })
  })
}

