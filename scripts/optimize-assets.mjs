import { copyFile, mkdir, readdir, rm } from 'node:fs/promises'
import { basename, dirname, extname, join, relative, resolve } from 'node:path'
import sharp from 'sharp'

const imageExtensions = new Set(['.png', '.jpg', '.jpeg', '.webp'])
const outputRoot = resolve('.generated-assets')

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true }).catch((error) => {
    if (error.code === 'ENOENT') return []
    throw error
  })
  const files = await Promise.all(entries.map((entry) => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? walk(path) : path
  }))
  return files.flat()
}

await rm(outputRoot, { recursive: true, force: true })
await mkdir(join(outputRoot, 'models'), { recursive: true })

const environmentRoot = resolve('enviroments')
const environmentFiles = (await walk(environmentRoot))
  .filter((file) => imageExtensions.has(extname(file).toLowerCase()))

for (const source of environmentFiles) {
  const relativePath = relative(environmentRoot, source)
  const output = join(outputRoot, 'enviroments', dirname(relativePath), `${basename(relativePath, extname(relativePath))}.webp`)
  await mkdir(dirname(output), { recursive: true })
  await sharp(source)
    .resize({ width: 2048, withoutEnlargement: true })
    .webp({ quality: 82, effort: 5, smartSubsample: true })
    .toFile(output)
}

const modelRoot = resolve('models')
const allModelFiles = await walk(modelRoot)
const modelFiles = allModelFiles
  .filter((file) => imageExtensions.has(extname(file).toLowerCase()))

for (const source of allModelFiles.filter((file) => extname(file).toLowerCase() === '.glb')) {
  const output = join(outputRoot, 'models', relative(modelRoot, source))
  await mkdir(dirname(output), { recursive: true })
  await copyFile(source, output)
}

for (const source of modelFiles) {
  const relativePath = relative(modelRoot, source)
  const output = join(outputRoot, 'models', dirname(relativePath), `${basename(relativePath, extname(relativePath))}.webp`)
  await mkdir(dirname(output), { recursive: true })
  await sharp(source)
    .resize(100, 100, { fit: 'cover', withoutEnlargement: false })
    .webp({ quality: 78, effort: 5, smartSubsample: true })
    .toFile(output)
}

console.log(`Optimized ${environmentFiles.length} environment(s) and ${modelFiles.length} thumbnail(s); copied ${allModelFiles.length - modelFiles.length} model file(s).`)
