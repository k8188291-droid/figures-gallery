// The GLB cache name is unchanged on purpose: models stay cached permanently
// by URL, so returning visitors keep their downloaded models across deploys.
const MODEL_CACHE = '3d-gallery-models-v1'
// v2: v1 could hold a redirected app-shell Response (see below) that broke
// every later visit. Activating this worker deletes the v1 entry.
const PAGE_CACHE = '3d-gallery-pages-v2'
const CACHE_PREFIXES = ['3d-gallery-models-', '3d-gallery-pages-']

// The app shell is stored under the scope root ("./"), its real URL. Hosts
// such as Cloudflare Pages answer /index.html with a 308 redirect to /, and a
// redirected Response must never answer a navigation: the browser rejects it
// ("a redirected response was used for a request whose redirect mode is not
// 'follow'") and the page fails to load.
const shellUrl = () => self.registration.scope

// Only plain, successful, same-origin responses are stored.
const isCacheable = (response) => response.ok
  && response.status === 200
  && response.type === 'basic'
  && !response.redirected

// Rebuild a redirected Response as a clean one so it can answer a navigation.
async function clean(response) {
  if (!response.redirected) return response
  return new Response(await response.blob(), {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  })
}

async function storeShell(response) {
  if (!isCacheable(response)) return
  const cache = await caches.open(PAGE_CACHE)
  await cache.put(shellUrl(), response)
}

async function cachedShell() {
  const cache = await caches.open(PAGE_CACHE)
  const cached = await cache.match(shellUrl())
  return cached ? clean(cached) : undefined
}

// Refresh the offline copy of the app shell.
async function refreshShell() {
  const url = new URL(shellUrl())
  url.searchParams.set('__sw_check', Date.now().toString())
  const response = await fetch(url, { cache: 'no-store' })
  if (response.ok) await storeShell(await clean(response))
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
    event.waitUntil(refreshShell().catch(() => undefined))
  }
})

// Network-first for navigations: always serve the latest page when online,
// fall back to the stored shell when offline.
async function handleNavigation(request) {
  try {
    const response = await fetch(request)
    // Redirects reach a navigation as opaque redirects; pass them through so
    // the browser follows them, but never store them.
    if (isCacheable(response)) await storeShell(response.clone()).catch(() => undefined)
    return response
  } catch (error) {
    const cached = await cachedShell()
    if (cached) return cached
    throw error
  }
}

// Cache-first for GLBs, keyed by URL. Replacing a model under the same name
// keeps serving the cached copy to returning visitors; publish changes under
// a new file name.
async function handleModel(request) {
  const cache = await caches.open(MODEL_CACHE)
  const cached = await cache.match(request)
  if (cached && !cached.redirected) return cached

  const response = await fetch(request)
  if (isCacheable(response)) await cache.put(request, response.clone())
  return response
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return

  const url = new URL(event.request.url)
  const sameOrigin = url.origin === self.location.origin
  // A Service Worker sees every GET request, including JS, CSS, images, fonts,
  // API calls, and GLB files. `mode === 'navigate'` limits the app-shell
  // handling to top-level document navigations, including SPA routes that do
  // not end in index.html. Hash-only changes do not make a network request and
  // therefore do not trigger this fetch handler.
  const isNavigation = event.request.mode === 'navigate' && sameOrigin
  const isModel = sameOrigin && url.pathname.toLowerCase().endsWith('.glb')
  const isApi = sameOrigin && url.pathname.startsWith(new URL('api/', self.registration.scope).pathname)

  // The model list (api/models) always goes to the network so models added to
  // or removed from the bucket appear on the next page load. Not calling
  // respondWith() leaves the request to the browser.
  if (isApi) return

  if (isNavigation) {
    event.respondWith(handleNavigation(event.request))
    return
  }

  // Range requests are left to the network: partial (206) responses cannot be
  // cached.
  if (!isModel || event.request.headers.has('range')) return

  event.respondWith(handleModel(event.request))
})
