// Shared helpers for the R2-backed model routes.

export const THUMBNAIL_EXTENSIONS = ['.webp', '.png', '.jpg', '.jpeg']

const CONTENT_TYPES = {
  '.glb': 'model/gltf-binary',
  '.gltf': 'model/gltf+json',
  '.bin': 'application/octet-stream',
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.ktx2': 'image/ktx2',
}

export function extensionOf(key) {
  const name = key.slice(key.lastIndexOf('/') + 1)
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot).toLowerCase() : ''
}

export function contentTypeFor(key) {
  return CONTENT_TYPES[extensionOf(key)] ?? 'application/octet-stream'
}

// Encode every path segment so names with spaces, '#', '?' or '%' stay valid
// URLs. For ordinary names this matches encodeURI(), so URLs (and therefore
// Service Worker cache keys) are the same as the old build-time manifest.
export function modelUrl(key) {
  return `models/${key.split('/').map(encodeURIComponent).join('/')}`
}
