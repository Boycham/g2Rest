import type { Role } from './hud'

/** floor.json staff ids the glasses connect as by default (VITE_FS_STAFF overrides the server's). */
export const DEFAULT_STAFF: Record<Role, string> = { server: 's1', manager: 'm1' }

/**
 * The backend WebSocket URL for a role: `base?token=&role=&staff=` (backend/NOTES.md, Sync 1).
 * Query params already on `base` win, so a hand-written VITE_BACKEND_URL still works. The token
 * is a dev token and ships in the WebView bundle (glasses/NOTES.md).
 */
export function backendUrl(base: string, role: Role, token = '', serverStaff = ''): string {
  const url = new URL(base)
  const staff = role === 'server' && serverStaff ? serverStaff : DEFAULT_STAFF[role]
  const defaults: [string, string][] = [
    ['token', token],
    ['role', role],
    ['staff', staff],
  ]
  for (const [k, v] of defaults) if (v && !url.searchParams.has(k)) url.searchParams.set(k, v)
  return url.toString()
}

/** The URL without its token, for logs and the phone screen. */
export function redactToken(url: string): string {
  const u = new URL(url)
  if (u.searchParams.has('token')) u.searchParams.set('token', '…')
  return u.toString()
}
