// Page state built from GET /state and kept live by hub messages. Pure: no DOM, no fetch,
// so it runs under `node --test`.

export const COURSE_ORDER = { appetizer: 0, main: 1, dessert: 2 }
export const TASK_ORDER = { assigned: 0, accepted: 1, bounced: 2, done: 3 }

export function emptyState() {
  return { tables: {}, tasks: {}, orders: {}, alerts: {}, pass: null, at: Date.now() }
}

/** Full resync from GET /state (which includes the pass on backends that have one). */
export function fromSnapshot(snap, prev = emptyState(), now = Date.now()) {
  const s = { ...emptyState(), pass: snap.pass ? withAt(snap.pass, now) : prev.pass, at: now }
  for (const t of snap.tables ?? []) s.tables[t.table] = { ...t, at: now }
  for (const t of snap.tasks ?? []) s.tasks[t.id] = t
  for (const o of snap.orders ?? []) s.orders[o.orderId] = o
  for (const a of snap.alerts ?? []) s.alerts[a.id] = { ...a, at: now }
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
      s.pass = withAt(msg, now)
      return s
    }
    default:
      return state
  }
}

/** A pass body (GET /pass, POST /pass/up or pass.state) stamped with when it arrived. */
export function withAt(pass, now = Date.now()) {
  const { type: _type, ...body } = pass
  return { ...body, at: now }
}

/**
 * Holds worth showing at the pass: courses where some plates are up and others are not, with
 * the dishes they wait on. A course with nothing up yet is still cooking, not held.
 */
export function activeHolds(pass) {
  const plates = pass?.plates ?? []
  return (pass?.holds ?? []).filter((hd) =>
    plates.some((p) => p.table === hd.table && p.course === hd.course && p.status === 'up'),
  )
}

/** Seconds since `sinceSec` was measured, ticking client-side between updates. */
export function liveSince(entry, now = Date.now()) {
  return entry.sinceSec + Math.max(0, Math.floor((now - entry.at) / 1000))
}

/** Alert text with the hub's "{elapsed}" placeholder filled in. */
export function alertText(alert, now = Date.now()) {
  return alert.text.replace('{elapsed}', fmtSince(liveSince(alert, now)))
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
 * An order as kitchen rows: each line with its index, course and temperature from the menu,
 * sorted by course then seat. `plate` is that line's status at the pass ('waiting', 'up',
 * 'running'), or null while the order is a draft. `conflicts` lists the seat's allergens that
 * the dish contains, uppercase.
 */
export function ticketRows(order, menu, pass) {
  const byName = new Map((menu?.dishes ?? []).map((d) => [d.name, d]))
  const plates = new Map(
    (pass?.plates ?? []).filter((p) => p.orderId === order.orderId).map((p) => [p.line, p.status]),
  )
  return order.lines
    .map((line, index) => {
      const dish = byName.get(line.dish)
      const seatAllergens = seatAllergies(order.allergies ?? [], line.seat).map((a) => a.allergen.toUpperCase())
      const contains = new Set((dish?.allergens ?? []).map((a) => a.toUpperCase()))
      return {
        ...line,
        index,
        course: dish?.course ?? 'main',
        temperature: dish?.temperature ?? '',
        plate: plates.get(index) ?? null,
        conflicts: seatAllergens.filter((a) => contains.has(a)),
      }
    })
    .sort((a, b) => (COURSE_ORDER[a.course] ?? 9) - (COURSE_ORDER[b.course] ?? 9) || a.seat - b.seat)
}

/** Allergies that touch the given seat. */
export function seatAllergies(allergies, seat) {
  return allergies.filter((a) => !a.seats?.length || a.seats.includes(seat))
}
