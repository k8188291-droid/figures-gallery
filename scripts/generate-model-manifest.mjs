import { readdir, writeFile, mkdir } from 'node:fs/promises'
import { dirname, extname, join, relative, resolve, sep } from 'node:path'

const root = resolve('models')
const output = resolve('.generated-assets/models.js')

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(async (entry) => {
    const fullPath = join(directory, entry.name)
    return entry.isDirectory() ? walk(fullPath) : fullPath
  }))
  return files.flat()
}

const allFiles = await walk(root).catch((error) => {
  if (error.code === 'ENOENT') return []
  throw error
})

const portable = (path) => path.split(sep).join('/')
const imageExtensions = ['.png', '.jpg', '.jpeg', '.webp']
const relativeFiles = new Set(allFiles.map((file) => portable(relative(root, file))))

const models = allFiles
  .filter((file) => extname(file).toLowerCase() === '.glb')
  .map((file) => {
    const path = portable(relative(root, file))
    const base = path.slice(0, -extname(path).length)
    const thumbnailSource = imageExtensions
      .map((extension) => `${base}${extension}`)
      .find((candidate) => relativeFiles.has(candidate)) ?? null

    return {
      id: path,
      name: base.split('/').at(-1),
      folder: portable(dirname(path)) === '.' ? 'Root' : portable(dirname(path)),
      path: `models/${encodeURI(path)}`,
      thumbnail: thumbnailSource ? `models/${encodeURI(`${base}.webp`)}` : null,
    }
  })
  .sort((a, b) => a.id.localeCompare(b.id, 'zh-Hant', { numeric: true }))

const manifest = `window.MODEL_LIST = ${JSON.stringify(models, null, 2)};\n`
await mkdir(dirname(output), { recursive: true })
await writeFile(output, manifest)
console.log(`Generated model manifest with ${models.length} model(s).`)
