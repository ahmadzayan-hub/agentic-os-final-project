import { useEffect, useState } from 'react'

/** Text drafts survive reloads in this tab only. The owning view is keyed
 * by session; raw dataset contents never enter this storage. */
export function useSessionDraft(key: string, initial: () => string) {
  const [value, setValue] = useState(() => {
    try { return sessionStorage.getItem(`aos-draft:${key}`) ?? initial() }
    catch { return initial() }
  })
  useEffect(() => {
    try {
      if (value) sessionStorage.setItem(`aos-draft:${key}`, value)
      else sessionStorage.removeItem(`aos-draft:${key}`)
    } catch { /* Storage may be unavailable; the live draft still works. */ }
  }, [key, value])
  return [value, setValue] as const
}
