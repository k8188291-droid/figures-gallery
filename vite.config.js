import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteStaticCopy } from 'vite-plugin-static-copy'

function modelManifestPlugin(source) {
  const hash = createHash('sha256').update(source).digest('hex').slice(0, 8)
  const filename = `models.${hash}.js`
  let isBuild = false

  return {
    name: 'model-manifest',
    configResolved(config) {
      isBuild = config.command === 'build'
    },
    buildStart() {
      if (isBuild) this.emitFile({ type: 'asset', fileName: filename, source })
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (!request.url?.split('?')[0].endsWith(`/${filename}`)) return next()
        response.setHeader('Content-Type', 'text/javascript; charset=utf-8')
        response.end(source)
      })
    },
    transformIndexHtml() {
      return [{
        tag: 'script',
        attrs: { src: `./${filename}` },
        injectTo: 'body-prepend',
      }]
    },
  }
}

export default defineConfig(async ({ command }) => {
  const manifest = await readFile(resolve('.generated-assets/models.js'), 'utf8')

  return {
    // Relative asset URLs work on both custom domains and /repo-name/ GitHub Pages.
    base: './',
    plugins: [
      modelManifestPlugin(manifest),
      react(),
      viteStaticCopy({
        targets: [
          // Production serves GLBs and thumbnails from R2 through the
          // functions/models/ route, so they are not copied into dist. The
          // dev server still serves the local models/ folder.
          ...(command === 'serve' ? [{ src: '.generated-assets/models', dest: '.' }] : []),
          { src: '.generated-assets/enviroments', dest: '.' },
        ],
      }),
    ],
  }
})
