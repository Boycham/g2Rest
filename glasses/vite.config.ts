import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'

const FIXTURES = fileURLToPath(new URL('../backend/voice/fixtures/', import.meta.url))

/** DEV ONLY: serves the gitignored voice fixtures for the debug PCM path (src/debug-pcm.ts). */
function devFixtures(): Plugin {
  return {
    name: 'fs-dev-fixtures',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/dev-fixtures', (req, res) => {
        const name = (req.url ?? '').replace(/^\//, '')
        if (!/^[\w-]+\.pcm$/.test(name)) {
          res.statusCode = 400
          res.end('bad name')
          return
        }
        readFile(FIXTURES + name).then(
          buf => {
            res.setHeader('content-type', 'application/octet-stream')
            res.end(buf)
          },
          () => {
            res.statusCode = 404
            res.end('no such fixture (run backend/voice/make_fixtures.py)')
          },
        )
      })
    },
  }
}

export default defineConfig({
  // Env vars live in the one root .env (see the root .env.example).
  envDir: '..',
  plugins: [devFixtures()],
  // The menu is bundled from ../data/menu.json (src/ramp.ts).
  server: { host: true, port: 5173, fs: { allow: ['..'] } },
  build: { target: 'esnext' },
})
