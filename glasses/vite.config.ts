import { defineConfig } from 'vite'

export default defineConfig({
  // Env vars live in the one root .env (see the root .env.example).
  envDir: '..',
  server: { host: true, port: 5173 },
  build: { target: 'esnext' },
})
