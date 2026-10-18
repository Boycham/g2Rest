import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Two pages: the scroll story (index.html) and the manager dashboard (dashboard.html).
// The dashboard reuses ../client.js and ../state.js, the same modules the organizer and
// kitchen pages run, so the backend contract lives in one place.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { port: 5176, fs: { allow: ['..'] } },
  build: {
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.html'),
        dashboard: resolve(__dirname, 'dashboard.html'),
      },
    },
  },
})
