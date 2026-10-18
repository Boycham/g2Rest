import type { Role } from './hud'

/** floor.json staff ids the glasses connect as by default (VITE_FS_STAFF overrides the server's). */
export const DEFAULT_STAFF: Record<Role, string> = { server: 's1', manager: 'm1' }

/**
 * The backend WebSocket URL for a role: `base?token=&role=&staff=` (backend/NOTES.md, Sync 1).
 * The role picker always decides `role` and `staff`, even when a hand-written VITE_BACKEND_URL
 * already carries them: on a real G2 a packed URL with `role=server&staff=s1` kept the glasses
 * on server Ava whatever the picker said. A token already on `base` is kept. The token is a
 * dev token and ships in the WebView bundle (glasses/NOTES.md).
 */
export function backendUrl(base: string, role: Role, token = '', serverStaff = ''): string {
  const url = new URL(base)
  const staff = role === 'server' ? serverStaff || DEFAULT_STAFF.server : DEFAULT_STAFF[role]
  if (token && !url.searchParams.has('token')) url.searchParams.set('token', token)
  url.searchParams.set('role', role)
  url.searchParams.set('staff', staff)
  return url.toString()
}

/** The URL without its token, for logs and the phone screen. */
export function redactToken(url: string): string {
  const u = new URL(url)
  if (u.searchParams.has('token')) u.searchParams.set('token', '…')
  return u.toString()
}
