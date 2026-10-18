/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend WebSocket URL; also whitelist it in app.json. Never put API keys in VITE_ vars. */
  readonly VITE_BACKEND_URL?: string
  /** Backend FS_TOKEN, sent as ?token=. A dev token: it ships in the bundle. */
  readonly VITE_FS_TOKEN?: string
  /** floor.json staff id for the server role (default s1). */
  readonly VITE_FS_STAFF?: string
  /** Nod-to-accept tuning, `off` or `axis=y,sign=1,threshold=0.25,...` (src/nod.ts). */
  readonly VITE_FS_NOD?: string
}
