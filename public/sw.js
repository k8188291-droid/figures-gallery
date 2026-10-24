const MODEL_CACHE = '3d-gallery-models-v1'
const PAGE_CACHE = '3d-gallery-pages-v1'
const CACHE_PREFIXES = ['3d-gallery-models-', '3d-gallery-pages-']

const indexUrl = () => new URL('index.html', self.registration.scope).href

async function fetchLatestIndex() {
  const url = new URL(indexUrl())
  url.searchParams.set('__sw_check', Date.now().toString())
  return fetch(url, { cache: 'no-store' })
}

// Compare the cached app shell with a cache-busted copy from the host.
// Updating Cache Storage only affects future requests: a document that has
// already been delivered, parsed, and started cannot have its Response body
// replaced in place. Therefore, when a background check finds a new index,
// the page is notified and performs one reload so the next navigation receives
// the updated cached document.
async function checkIndex({ notify = true } = {}) {
  const cache = await caches.open(PAGE_CACHE)
  const cached = await cache.match(indexUrl())
  const latest = await fetchLatestIndex()
  if (!latest.ok) return false

  if (!cached) {
    await cache.put(indexUrl(), latest.clone())
    return false
  }

  const [cachedHtml, latestHtml] = await Promise.all([cached.text(), latest.clone().text()])
  if (cachedHtml === latestHtml) return false

  await cache.put(indexUrl(), latest.clone())
  if (notify) {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    clients.forEach((client) => client.postMessage({ type: 'INDEX_UPDATED' }))
  }
  return true
}

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => CACHE_PREFIXES.some((prefix) => key.startsWith(prefix))
          && key !== MODEL_CACHE
          && key !== PAGE_CACHE)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('message', (event) => {
  if (event.data?.type === 'CHECK_INDEX') {
    event.waitUntil(checkIndex().catch(() => false))
  }
})

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return

  const url = new URL(event.request.url)
  const sameOrigin = url.origin === self.location.origin
  // A Service Worker sees every GET request, including JS, CSS, images, fonts,
  // API calls, and GLB files. `mode === 'navigate'` limits the app-shell
  // response to top-level document navigations, including SPA routes that do
  // not end in index.html. Without this guard, an asset request could receive
  // HTML and fail to parse. Hash-only changes do not make a network request and
  // therefore do not trigger this fetch handler.
  const isNavigation = event.request.mode === 'navigate' && sameOrigin
  const isModel = sameOrigin && url.pathname.toLowerCase().endsWith('.glb')
  const isApi = sameOrigin && url.pathname.startsWith(new URL('api/', self.registration.scope).pathname)

  // The model list (api/models) is always fetched from the network so models
  // added to or removed from the bucket appear on the next page load. Not
  // calling respondWith() leaves the request to the browser.
  if (isApi) return

  if (isNavigation) {
    // Stale-while-revalidate keeps startup fast: return the cached page now and
    // check for a newer copy in the background. A network-first implementation
    // could return the latest Response directly and avoid a second reload, but
    // every navigation would then wait for the network and be slower offline.
    event.respondWith(
      caches.open(PAGE_CACHE).then(async (cache) => {
        const cached = await cache.match(indexUrl())
        if (cached) return cached

        const response = await fetch(event.request)
        if (response.ok) await cache.put(indexUrl(), response.clone())
        return response
      }),
    )
    event.waitUntil(checkIndex().catch(() => false))
    return
  }

  // GLBs are cached permanently by URL (cache-first). Replacing a model under
  // the same name therefore keeps serving the cached copy to returning
  // visitors; publish changes under a new file name. Range requests are left
  // to the network because partial (206) responses cannot be cached.
  if (!isModel || event.request.headers.has('range')) return

  event.respondWith(
    caches.open(MODEL_CACHE).then(async (cache) => {
      const cached = await cache.match(event.request)
      if (cached) return cached

      const response = await fetch(event.request)
      if (response.ok) await cache.put(event.request, response.clone())
      return response
    }),
  )
})
