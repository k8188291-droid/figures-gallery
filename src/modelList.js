// Loads the model list at startup.
//
// Production: GET api/models (a Pages Function that lists the R2 bucket), so
// models added, renamed or removed in the bucket show up without a rebuild.
// Fallback: the build-time list (window.MODEL_LIST, generated from the local
// models/ folder). It is used when the API is unavailable, e.g. `npm run dev`
// without Pages Functions, or when the request fails.
const API_TIMEOUT_MS = 8000

const isModelEntry = (entry) => entry
  && typeof entry.id === 'string'
  && typeof entry.name === 'string'
  && typeof entry.folder === 'string'
  && typeof entry.path === 'string'

async function fetchModelList() {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS)
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}api/models`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    // Dev servers answer unknown routes with index.html; treat that as "no API".
    if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Not JSON')
    const list = await response.json()
    if (!Array.isArray(list) || !list.every(isModelEntry)) throw new Error('Unexpected model list')
    return list
  } finally {
    clearTimeout(timer)
  }
}

export async function loadModelList() {
  try {
    return await fetchModelList()
  } catch (error) {
    if (import.meta.env.PROD) console.warn('Model API unavailable, using the build-time list.', error)
    return window.MODEL_LIST ?? []
  }
}
