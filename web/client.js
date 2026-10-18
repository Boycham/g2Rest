// Shared browser client for the organizer and kitchen pages: backend URL and token,
// fetch with a timeout, the live organizer socket, and a tiny element builder.
//
// Pages take ?api=http://host:8787&token=... . Without ?api, a page served over https (by the
// server's Caddy, at https://<host>/app/) talks to its own origin; served locally over http it
// talks to the dev backend on localhost:8787.

const params = new URLSearchParams(location.search)
const defaultApi = location.protocol === 'https:' ? location.origin : 'http://localhost:8787'
export const API = (params.get('api') ?? defaultApi).replace(/\/$/, '')
export const TOKEN = params.get('token') ?? ''
const TIMEOUT_MS = 4000

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

/** GET when body is undefined, POST otherwise. Throws ApiError (status 0 = network/timeout). */
export async function api(path, body) {
  const headers = { 'content-type': 'application/json' }
  if (TOKEN) headers.authorization = `Bearer ${TOKEN}`
  let res
  try {
    res = await fetch(API + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })
  } catch (e) {
    throw new ApiError(0, e.name === 'TimeoutError' ? 'backend timed out' : 'backend unreachable')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText)
  return data
}

/**
 * Organizer socket with reconnect. `staff=organizer` keeps the hub from treating this tab
 * as a server's glasses. onStatus(true) fires on every (re)connect so the page can resync.
 */
export function live(onMessage, onStatus) {
  const q = new URLSearchParams({ role: 'organizer', staff: 'organizer' })
  if (TOKEN) q.set('token', TOKEN)
  const url = `${API.replace(/^http/, 'ws')}/ws?${q}`
  let delay = 500
  const open = () => {
    const ws = new WebSocket(url)
    ws.onopen = () => {
      delay = 500
      onStatus(true)
    }
    ws.onmessage = (e) => {
      let msg
      try {
        msg = JSON.parse(e.data)
      } catch {
        console.warn('[fs] dropped non-JSON frame')
        return
      }
      onMessage(msg)
    }
    ws.onclose = () => {
      onStatus(false)
      setTimeout(open, delay)
      delay = Math.min(delay * 2, 8000)
    }
  }
  open()
}

/** h('div', {class: 'x', onclick}, child, 'text', [more]) -> Element. Text is never parsed as HTML. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v)
    else el.setAttribute(k, v === true ? '' : v)
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue
    el.append(c instanceof Node ? c : String(c))
  }
  return el
}

/** Connection pill + toast area shared by both pages. */
export function chrome() {
  const pill = document.getElementById('conn')
  const toast = document.getElementById('toast')
  let timer
  return {
    connected(ok) {
      pill.textContent = ok ? 'live' : 'reconnecting…'
      pill.dataset.ok = ok
    },
    error(msg) {
      toast.textContent = msg
      toast.hidden = false
      clearTimeout(timer)
      timer = setTimeout(() => (toast.hidden = true), 5000)
    },
  }
}
