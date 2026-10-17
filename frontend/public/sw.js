/* Agentic OS service worker: cache-first for immutable hashed assets,
   network-only for the API (session data must never be cached), and a
   network-first app shell so updates arrive on the next load. */
// Bumped with design system v2 (ADR 0023): the icons are cached first and
// would otherwise keep the old colours on returning devices.
const CACHE = 'aos-v3'

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(['/', '/artwork/evidence-still-life.webp'])))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))),
    ),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin) return
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    return // API traffic is always live and never cached.
  }
  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/icons/') || url.pathname.startsWith('/artwork/')) {
    event.respondWith(
      caches.match(event.request).then(
        (hit) =>
          hit ||
          fetch(event.request).then((response) => {
            const copy = response.clone()
            if (response.ok) caches.open(CACHE).then((cache) => cache.put(event.request, copy))
            return response
          }),
      ),
    )
    return
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (url.pathname === '/') {
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put('/', copy))
        }
        return response
      })
      .catch(() => caches.match('/')),
  )
})

