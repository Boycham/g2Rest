/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend WebSocket URL; also whitelist it in app.json. Never put API keys in VITE_ vars. */
  readonly VITE_BACKEND_URL?: string
}
