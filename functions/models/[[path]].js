// GET/HEAD /models/<folder>/<file>: stream the object from the R2 bucket
// bound as MODELS. Supports conditional requests (ETag / If-None-Match) and
// single byte ranges.
import { contentTypeFor, extensionOf } from '../_lib/models.js'

// The Service Worker caches GLBs permanently by URL (cache-first), so a model
// replaced under the same name stays cached for returning visitors; rename the
// file to publish a change. The HTTP cache lifetimes below only matter for
// browsers without the Service Worker. Pages Function responses are not cached
// by the Cloudflare CDN, so new visitors always receive the current object.
const CACHE_CONTROL = {
  '.glb': 'public, max-age=86400',
  default: 'public, max-age=300',
}

function objectKey(request) {
  const { pathname } = new URL(request.url)
  const rest = pathname.replace(/^\/models\//, '')
  try {
    return rest.split('/').map(decodeURIComponent).join('/')
  } catch {
    return null
  }
}

function responseHeaders(object, key) {
  const headers = new Headers()
  object.writeHttpMetadata(headers)
  if (!headers.has('Content-Type') || headers.get('Content-Type') === 'application/octet-stream') {
    headers.set('Content-Type', contentTypeFor(key))
  }
  headers.set('ETag', object.httpEtag)
  headers.set('Last-Modified', object.uploaded.toUTCString())
  headers.set('Accept-Ranges', 'bytes')
  headers.set('Cache-Control', CACHE_CONTROL[extensionOf(key)] ?? CACHE_CONTROL.default)
  return headers
}

const notFound = () => new Response('Not found', {
  status: 404,
  headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' },
})

export async function onRequest({ request, env }) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD' } })
  }
  if (!env.MODELS) return new Response('R2 binding MODELS is not configured', { status: 500 })

  const key = objectKey(request)
  if (!key || key.endsWith('/') || key.split('/').some((part) => part === '' || part === '.' || part === '..')) {
    return notFound()
  }

  if (request.method === 'HEAD') {
    const object = await env.MODELS.head(key)
    if (!object) return notFound()
    const headers = responseHeaders(object, key)
    headers.set('Content-Length', String(object.size))
    return new Response(null, { headers })
  }

  const hasRange = request.headers.has('Range')
  let object
  try {
    object = await env.MODELS.get(key, {
      onlyIf: request.headers,
      ...(hasRange ? { range: request.headers } : {}),
    })
  } catch {
    // R2 rejects unsatisfiable or malformed ranges.
    const head = await env.MODELS.head(key)
    if (!head) return notFound()
    return new Response('Range not satisfiable', { status: 416, headers: { 'Content-Range': `bytes */${head.size}` } })
  }
  if (!object) return notFound()

  const headers = responseHeaders(object, key)

  // A failed precondition returns metadata without a body.
  if (!('body' in object) || !object.body) {
    const conditional = request.headers.has('If-None-Match') || request.headers.has('If-Modified-Since')
    return new Response(null, { status: conditional ? 304 : 412, headers })
  }

  if (hasRange && object.range) {
    const { size } = object
    let offset = object.range.offset ?? 0
    let length = object.range.length ?? size - offset
    if (object.range.suffix !== undefined) {
      length = Math.min(object.range.suffix, size)
      offset = size - length
    }
    length = Math.min(length, size - offset)
    headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${size}`)
    headers.set('Content-Length', String(length))
    return new Response(object.body, { status: 206, headers })
  }

  headers.set('Content-Length', String(object.size))
  return new Response(object.body, { headers })
}
