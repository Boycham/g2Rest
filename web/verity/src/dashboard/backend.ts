// The dashboard's live connection: GET /floor once, GET /state on every (re)connect, hub
// messages through the shared reducer (web/state.js), the event log for routing history,
// and /stats + /health on a slow poll. One store outside React; components read it with
// useSyncExternalStore. Data changes call `before` listeners first, so the board can record
// card positions for its GSAP Flip.
import { useEffect, useState, useSyncExternalStore } from 'react'
import { api, live, traced } from '../../../client.js'
import { apply, emptyState, fromSnapshot } from '../../../state.js'

export type Staff = { id: string; name: string; sections: string[] }
export type Floor = {
  restaurant: string
  sections: { id: string; server: string }[]
  servers: Staff[]
  manager: { id: string; name: string }
  tables: { id: string; section: string; seats: number; x: number; y: number }[]
}
export type Task = {
  id: string
  kind: string
  table: string
  items: { qty: number; dish: string }[]
  allergies: { allergen: string; seats?: number[] }[]
  notes: string[]
  state: 'assigned' | 'accepted' | 'bounced' | 'done'
  assignee: string
  createdAt: string
  backendState?: string
}
export type Alert = { id: string; level: string; text: string; table?: string; sinceSec: number; at: number }
export type Order = {
  orderId: string
  table: string | null
  status?: string
  lines: { seat: number; dish: string; qty: number }[]
  summary?: string | null
  answers?: { seat?: number | null; q: string; a: string; known?: boolean }[] | null
  uncertain?: string[] | null
  notes?: string[] | null
}
export type State = {
  tables: Record<string, { table: string; status: string; sinceSec: number; urgency: number; at: number }>
  tasks: Record<string, Task>
  orders: Record<string, Order>
  alerts: Record<string, Alert>
}
export type LogEvent = { seq: number; at: string; type: string; data: Record<string, any> }
export type Stats = {
  doneSec: number
  escalationSec?: number
  servers: { id: string; name: string; done: number; avgSec: number | null; open: { taskId: string; kind: string; table: string; state: string; heldSec: number }[] }[]
}

export type Snapshot = {
  floor: Floor | null
  state: State
  events: LogEvent[]
  stats: Stats | null
  online: Set<string>
  /** null until the first connect attempt settles */
  connected: boolean | null
  /** when the socket tries again (ms since epoch), while disconnected */
  retryAt: number | null
  toast: string | null
}

type Listener = () => void

class Store {
  snap: Snapshot = {
    floor: null,
    state: emptyState(),
    events: [],
    stats: null,
    online: new Set(),
    connected: null,
    retryAt: null,
    toast: null,
  }
  private listeners = new Set<Listener>()
  private before = new Set<Listener>()
  private socket: { retry(): void } | null = null
  private seq = 0
  private eventsTimer: ReturnType<typeof setTimeout> | null = null
  private toastTimer: ReturnType<typeof setTimeout> | null = null

  subscribe = (fn: Listener) => {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }
  onBeforeChange = (fn: Listener) => {
    this.before.add(fn)
    return () => {
      this.before.delete(fn)
    }
  }
  get = () => this.snap

  private set(patch: Partial<Snapshot>, data = true) {
    if (data) for (const fn of this.before) fn()
    this.snap = { ...this.snap, ...patch }
    for (const fn of this.listeners) fn()
  }

  error(msg: string) {
    this.set({ toast: msg }, false)
    if (this.toastTimer) clearTimeout(this.toastTimer)
    this.toastTimer = setTimeout(() => this.set({ toast: null }, false), 5000)
  }

  /** A user action as its own Sentry trace; failures become a toast, never a throw. */
  async act<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    try {
      return await traced(label, fn)
    } catch (e) {
      this.error(`${label}: ${(e as Error).message}`)
      return undefined
    }
  }

  async start() {
    try {
      this.set({ floor: await api('/floor') }, false)
    } catch (e) {
      this.set({ connected: false, retryAt: Date.now() + 2000 }, false)
      setTimeout(() => this.start(), 2000)
      return
    }
    this.socket = live(
      (msg: { type: string }) => {
        this.set({ state: apply(this.snap.state, msg) })
        if (msg.type.startsWith('task.') || msg.type === 'alert') this.pullEvents()
      },
      (ok: boolean, retryInMs?: number) => {
        this.set({ connected: ok, retryAt: ok ? null : Date.now() + (retryInMs ?? 500) }, false)
        if (ok) this.resync()
      },
    )
    this.pollHealth()
    this.pollStats()
    setInterval(() => this.pollHealth(), 4000)
    setInterval(() => this.pollStats(), 5000)
    setInterval(() => this.pullEvents(), 3000)
  }

  retry() {
    this.socket?.retry()
    this.resync()
  }

  async resync() {
    try {
      const snap = await api('/state')
      // A reset (or a new backend) restarts the event log: start reading it again from 0.
      if (typeof snap.events === 'number' && snap.events < this.seq) {
        this.seq = 0
        this.set({ events: [] })
      }
      this.set({ state: fromSnapshot(snap, this.snap.state as any) })
      this.pullEvents(0)
    } catch (e) {
      this.error(`Load state: ${(e as Error).message}`)
    }
  }

  /** Read new event-log entries (debounced, so a burst of frames costs one request). */
  pullEvents(wait = 120) {
    if (this.eventsTimer) return
    this.eventsTimer = setTimeout(async () => {
      this.eventsTimer = null
      try {
        const fresh: LogEvent[] = await api(`/events?since=${this.seq}`)
        if (!fresh.length) return
        this.seq = fresh[fresh.length - 1].seq
        this.set({ events: [...this.snap.events, ...fresh].slice(-2000) })
      } catch {
        // the socket status and the health poll already say when the backend is down
      }
    }, wait)
  }

  async pollHealth() {
    try {
      const h = await api('/health')
      const online = new Set<string>(h.online ?? [])
      const same = online.size === this.snap.online.size && [...online].every((s) => this.snap.online.has(s))
      if (!same) this.set({ online })
    } catch {
      /* shown by the socket status */
    }
  }

  async pollStats() {
    try {
      this.set({ stats: await api('/stats') })
    } catch {
      /* keep the last numbers */
    }
  }

  dispatch(body: { kind: string; table: string; notes: string[]; assignee: string | null }) {
    return this.act('Dispatch', () => api('/tasks', body))
  }

  reroute(taskId: string, to: string | null) {
    return this.act('Reroute', () => api(`/tasks/${taskId}/reroute`, { to }))
  }

  tableStatus(table: string, status: string) {
    return this.act('Table status', () => api(`/tables/${table}/status`, { status }))
  }
}

export const store = new Store()

export function useBackend(): Snapshot {
  return useSyncExternalStore(store.subscribe, store.get)
}

/** Date.now(), refreshed every `ms` (for countdown rings and "accepted 0:42 ago"). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}
