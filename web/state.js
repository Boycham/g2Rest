// Page state built from GET /state and kept live by hub messages. Pure: no DOM, no fetch,
// so it runs under `node --test`.

export const COURSE_ORDER = { appetizer: 0, main: 1, dessert: 2 }
export const TASK_ORDER = { assigned: 0, accepted: 1, bounced: 2, done: 3 }

export function emptyState() {
  return { tables: {}, tasks: {}, orders: {}, alerts: {}, pass: null, at: Date.now() }
}

/** Full resync from GET /state. `pass` is kept: it comes from GET /pass, not /state. */
export function fromSnapshot(snap, prev = emptyState(), now = Date.now()) {
  const s = { ...emptyState(), pass: prev.pass, at: now }
  for (const t of snap.tables ?? []) s.tables[t.table] = { ...t, at: now }
  for (const t of snap.tasks ?? []) s.tasks[t.id] = t
  for (const o of snap.orders ?? []) s.orders[o.orderId] = o
  for (const a of snap.alerts ?? []) s.alerts[a.id] = a
  return s
}

/** Apply one hub message. Returns a new state; unknown types leave it unchanged. */
export function apply(state, msg, now = Date.now()) {
  const s = { ...state, at: now }
  switch (msg.type) {
    case 'task.assigned':
    case 'task.updated': {
      // Keep backend-only fields (backendState, history) until the next /state resync.
      const prev = s.tasks[msg.task.id] ?? {}
      const backendState = prev.state === msg.task.state ? prev.backendState : undefined
      s.tasks = { ...s.tasks, [msg.task.id]: { ...prev, ...msg.task, backendState } }
      return s
    }
    case 'floor.state': {
      s.tables = {}
      for (const t of msg.tables) s.tables[t.table] = { ...t, at: now }
      return s
    }
    case 'alert': {
      s.alerts = { ...s.alerts }
      if (msg.cleared) delete s.alerts[msg.id]
      else s.alerts[msg.id] = { ...msg, at: now }
      return s
    }
    case 'order.draft': {
      const prev = s.orders[msg.orderId] ?? { status: 'draft' }
      const { type: _type, ...order } = msg
      s.orders = { ...s.orders, [msg.orderId]: { ...prev, ...order } }
      return s
    }
    case 'order.fired': {
      s.orders = { ...s.orders, [msg.order.orderId]: msg.order }
      return s
    }
    case 'order.closed': {
      const prev = s.orders[msg.orderId]
      if (!prev) return state
      s.orders = { ...s.orders, [msg.orderId]: { ...prev, status: msg.status } }
      return s
    }
    case 'pass.state': {
      const { type: _type, ...pass } = msg
      s.pass = pass
      return s
    }
    default:
      return state
  }
}

/** Seconds since `sinceSec` was measured, ticking client-side between updates. */
export function liveSince(entry, now = Date.now()) {
  return entry.sinceSec + Math.max(0, Math.floor((now - entry.at) / 1000))
}

export function fmtSince(sec) {
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

/** Open tasks first (by state, then newest), then the finished ones. */
export function boardTasks(state) {
  return Object.values(state.tasks).sort(
    (a, b) =>
      (TASK_ORDER[a.state] ?? 9) - (TASK_ORDER[b.state] ?? 9) ||
      String(b.createdAt).localeCompare(String(a.createdAt)),
  )
}

/** "2× Halibut, Soup" */
export function itemsText(items) {
  return items.map((i) => (i.qty > 1 ? `${i.qty}× ${i.dish}` : i.dish)).join(', ')
}

/** "SHELLFISH s3 · DAIRY s1+2", or '' when none. */
export function allergyText(allergies) {
  return allergies
    .map((a) => (a.seats?.length ? `${a.allergen} s${a.seats.join('+')}` : a.allergen))
    .join(' · ')
}

/**
 * A fired order as kitchen rows: each line with its index, course and temperature from the
 * menu, sorted by course then seat. `up` is true when the pass already has that line.
 */
export function ticketRows(order, menu, pass) {
  const byName = new Map((menu?.dishes ?? []).map((d) => [d.name, d]))
  const upLines = new Set(
    (pass?.plates ?? []).filter((p) => p.orderId === order.orderId).map((p) => p.line),
  )
  return order.lines
    .map((line, index) => {
      const dish = byName.get(line.dish)
      return {
        ...line,
        index,
        course: dish?.course ?? 'main',
        temperature: dish?.temperature ?? '',
        up: upLines.has(index),
      }
    })
    .sort((a, b) => (COURSE_ORDER[a.course] ?? 9) - (COURSE_ORDER[b.course] ?? 9) || a.seat - b.seat)
}

/** Allergies that touch the given seat. */
export function seatAllergies(allergies, seat) {
  return allergies.filter((a) => !a.seats?.length || a.seats.includes(seat))
}
