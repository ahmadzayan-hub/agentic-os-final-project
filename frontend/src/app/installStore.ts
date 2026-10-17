import { useSyncExternalStore } from 'react'

interface InstallPrompt extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}
let state: { prompt: InstallPrompt | null; installed: boolean } = { prompt: null, installed: false }
const listeners = new Set<() => void>()
let initialized = false
function emit() { listeners.forEach((listener) => listener()) }

/** Capture the browser event at boot, even before Preferences is opened. */
export function initializeInstall() {
  if (initialized) return
  initialized = true
  state = { ...state, installed: window.matchMedia('(display-mode: standalone)').matches || Boolean((navigator as Navigator & { standalone?: boolean }).standalone) }
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    state = { ...state, prompt: event as InstallPrompt }; emit()
  })
  window.addEventListener('appinstalled', () => { state = { prompt: null, installed: true }; emit() })
}
export function clearInstallPrompt() { state = { ...state, prompt: null }; emit() }
export function useInstall() {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => state)
}
