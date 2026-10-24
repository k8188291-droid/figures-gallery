// GET /api/models: list the R2 bucket bound as MODELS and return the model
// manifest in the same shape the build-time window.MODEL_LIST used:
//   [{ id, name, folder, path, thumbnail }]
// Every `<folder>/<name>.glb` object becomes one entry. A same-name .webp
// (or .png / .jpg / .jpeg) next to it becomes the thumbnail.
import { THUMBNAIL_EXTENSIONS, extensionOf, modelUrl } from '../_lib/models.js'

const LIST_CACHE_SECONDS = 30

async function listAllKeys(bucket) {
  const keys = []
  let cursor
  do {
    const page = await bucket.list({ cursor, limit: 1000 })
    for (const object of page.objects) keys.push(object.key)
    cursor = page.truncated ? page.cursor : undefined
  } while (cursor)
  return keys
}

const collator = new Intl.Collator('zh-Hant', { numeric: true })

export function buildManifest(keys) {
  const available = new Set(keys)
  return keys
    .filter((key) => extensionOf(key) === '.glb' && !key.endsWith('/'))
    .map((key) => {
      const base = key.slice(0, -'.glb'.length)
      const slash = key.lastIndexOf('/')
      const thumbnailKey = THUMBNAIL_EXTENSIONS
        .flatMap((extension) => [`${base}${extension}`, `${base}${extension.toUpperCase()}`])
        .find((candidate) => available.has(candidate))
      return {
        id: key,
        name: base.slice(slash + 1),
        folder: slash === -1 ? 'Root' : key.slice(0, slash),
        path: modelUrl(key),
        thumbnail: thumbnailKey ? modelUrl(thumbnailKey) : null,
      }
    })
    .sort((a, b) => collator.compare(a.folder, b.folder) || collator.compare(a.name, b.name))
}

export async function onRequestGet({ env }) {
  if (!env.MODELS) {
    return Response.json({ error: 'R2 binding MODELS is not configured' }, { status: 500, headers: { 'Cache-Control': 'no-store' } })
  }
  try {
    const models = buildManifest(await listAllKeys(env.MODELS))
    return Response.json(models, {
      headers: { 'Cache-Control': `public, max-age=${LIST_CACHE_SECONDS}` },
    })
  } catch (error) {
    return Response.json({ error: 'Failed to list models' }, { status: 502, headers: { 'Cache-Control': 'no-store' } })
  }
}
