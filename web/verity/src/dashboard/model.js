// Manager dashboard view model: turns the backend's state, event log, /stats and /health into
// what the Paper design draws (board columns, card states, table tones, the routing log).
// Pure: no DOM, no fetch, so `node --test` runs it.

export const KINDS = ['RUN', 'CLEAR', 'CHECK', 'SEAT', 'ORDER']
export const KIND_LABEL = {
  RUN: 'Pick up food',
  CLEAR: 'Clear table',
  CHECK: 'Check on table',
  SEAT: 'Seat party',
  ORDER: 'Take order',
}
export const COLUMNS = [
  { id: 'unassigned', label: 'Unassigned', tone: 'stone' },
  { id: 'waiting', label: 'Waiting for accept', tone: 'bone' },
  { id: 'accepted', label: 'Accepted', tone: 'leaf' },
  { id: 'done', label: 'Done', tone: 'stone' },
]
const DONE_SHOWN = 6

export function kindLabel(kind) {
  return KIND_LABEL[kind] ?? kind
}

/** "m:ss" (or "h:mm:ss" past an hour) for a duration in seconds. */
export function clock(sec) {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const pad = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`
}

/** "02:48": the zero-padded form the design uses for done times. */
export function clock2(sec) {
  const s = Math.max(0, Math.round(sec))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export function staffName(floor, id) {
  if (!id) return 'nobody'
  if (!floor) return id
  if (floor.manager?.id === id) return floor.manager.name
  return floor.servers.find((s) => s.id === id)?.name ?? id
}

export function staffList(floor) {
  if (!floor) return []
  return [...floor.servers.map((s) => ({ ...s, role: 'server' })), { ...floor.manager, sections: [], role: 'manager' }]
}

/** "T4" -> "04", the way the design numbers tables. */
export function tableNo(id) {
  const n = String(id).replace(/\D/g, '')
  return n ? n.padStart(2, '0') : String(id)
}

// ---------- the event log ----------

/** Wall-clock ms of an event (the log's top-level `at` is ISO). */
const ms = (e) => Date.parse(e.at)

/** Task events from GET /events, grouped by task in log order. */
export function timelines(events) {
  const out = new Map()
  for (const e of events) {
    if (!e.type.startsWith('task.') || !e.data?.taskId) continue
    const list = out.get(e.data.taskId) ?? []
    list.push({ ...e.data, seq: e.seq, type: e.type.slice(5), at: ms(e), mono: e.data.at })
    out.set(e.data.taskId, list)
  }
  return out
}

/** alertId -> taskId, from the log's alert.raised events. */
export function alertTasks(events) {
  const out = new Map()
  for (const e of events) if (e.type === 'alert.raised' && e.data?.alertId) out.set(e.data.alertId, e.data.taskId)
  return out
}

/** The task an alert is about: from the log, else a task id inside the alert id ("slow-task-1a2b3c"). */
export function alertTask(alert, links, tasks) {
  const viaLog = links.get(alert.id)
  if (viaLog && tasks[viaLog]) return viaLog
  return Object.keys(tasks).find((id) => alert.id.endsWith(id)) ?? null
}

// ---------- cards ----------

/**
 * One task as the board draws it.
 *  column:  unassigned (not on anyone's glasses yet) | waiting | accepted | done
 *  variant: unassigned | waiting | escalated | bounced | accepted | done | reverted
 *  ring:    for waiting cards, seconds left before it moves on (negative = over the limit)
 */
export function card(task, timeline = [], ctx) {
  const { floor, now, escalationSec = 30, alerted = false } = ctx
  const name = staffName(floor, task.assignee)
  const last = timeline.at(-1)
  const since = (type) => [...timeline].reverse().find((e) => e.type === type)
  const base = {
    id: task.id,
    kind: task.kind,
    table: task.table,
    title: kindLabel(task.kind),
    assignee: task.assignee,
    name,
    ring: null,
  }

  if (task.state === 'done') {
    const done = since('done')
    const started = since('accepted') ?? since('sent') ?? timeline[0]
    const took = done && started ? (done.mono - started.mono) : null
    return {
      ...base,
      column: 'done',
      variant: 'done',
      subtitle: took == null ? `${name} · done` : `${name} · done in ${clock2(took)}`,
      at: done?.at ?? 0,
    }
  }

  if (task.state === 'accepted') {
    const acc = since('accepted')
    const reverted = /^(revert|back to)/.test(acc?.reason ?? '')
    const ago = acc ? clock((now - acc.at) / 1000) : ''
    return {
      ...base,
      column: 'accepted',
      variant: reverted ? 'reverted' : 'accepted',
      subtitle: reverted ? `${name} · reverted, accepted ${ago} ago` : `${name} · accepted ${ago} ago`,
      at: acc?.at ?? 0,
    }
  }

  // Waiting: on someone's glasses (sent) or not yet (queued, their glasses are offline).
  const queuedNow = last?.type === 'queued' || (!last && task.backendState === 'queued')
  const handIndex = timeline.findLastIndex((e) => e.type === 'queued')
  const before = handIndex > 0 ? timeline[handIndex - 1] : null
  const prev = before ? staffName(floor, before.assignee) : null
  const startedAt = (since('sent') ?? since('queued') ?? { at: Date.parse(task.createdAt) || now }).at
  const left = escalationSec - (now - startedAt) / 1000

  if (queuedNow) {
    return {
      ...base,
      column: 'unassigned',
      variant: 'unassigned',
      subtitle: task.assignee ? `Routing… ${name}'s glasses are offline` : 'Routing…',
      at: startedAt,
    }
  }
  const ring = { left, total: escalationSec }
  if (alerted || left < 0 || before?.type === 'escalated') {
    const slow = (before?.reason ?? '').startsWith('not done after')
    const why =
      before?.type === 'escalated' && prev
        ? `${prev} ${slow ? 'took too long' : "didn't accept"} · now ${name}`
        : `${name} · no accept`
    return { ...base, column: 'waiting', variant: 'escalated', subtitle: why, ring, at: startedAt }
  }
  if (before?.type === 'bounced' && (before.reason ?? '').startsWith('manager reroute')) {
    return { ...base, column: 'waiting', variant: 'waiting', subtitle: `Rerouted from ${prev} · ${name}`, ring, at: startedAt }
  }
  if (before?.type === 'bounced') {
    const reason = before.reason ?? ''
    const variant = reason.startsWith('revert') ? 'reverted' : 'bounced'
    const what = reason.startsWith('task.handoff')
      ? `${prev} handed off · ${name}`
      : variant === 'reverted'
        ? `${name} · handed back`
        : `${prev} bounced · now ${name}`
    return { ...base, column: 'waiting', variant, subtitle: what, ring, at: startedAt }
  }
  return { ...base, column: 'waiting', variant: 'waiting', subtitle: `${name} · waiting to accept`, ring, at: startedAt }
}

/**
 * The four board columns, open cards oldest first, done newest first (a few).
 * @returns {{ unassigned: any[], waiting: any[], accepted: any[], done: any[], doneTotal: number }}
 */
export function board(tasks, lines, ctx) {
  const cols = { unassigned: [], waiting: [], accepted: [], done: [], doneTotal: 0 }
  for (const t of Object.values(tasks)) {
    const c = card(t, lines.get(t.id), { ...ctx, alerted: ctx.alertedTasks?.has(t.id) })
    cols[c.column].push(c)
  }
  for (const k of ['unassigned', 'accepted']) cols[k].sort((a, b) => a.at - b.at)
  // Waiting: most urgent first (escalated, then least time left to accept).
  cols.waiting.sort(
    (a, b) => Number(b.variant === 'escalated') - Number(a.variant === 'escalated') || a.ring.left - b.ring.left,
  )
  cols.done.sort((a, b) => b.at - a.at)
  cols.doneTotal = cols.done.length
  cols.done = cols.done.slice(0, DONE_SHOWN)
  return cols
}

const TONE_RANK = { escalated: 4, waiting: 3, bounced: 3, unassigned: 3, reverted: 2, accepted: 2, idle: 0 }
const TONE_OF = {
  escalated: 'escalated',
  waiting: 'waiting',
  bounced: 'waiting',
  unassigned: 'waiting',
  reverted: 'accepted',
  accepted: 'accepted',
}

/** A table's tile: the most urgent open card decides its ring; `dashed` when a bounce is in play. */
export function tableTone(tableId, cols) {
  const open = [...cols.unassigned, ...cols.waiting, ...cols.accepted].filter((c) => c.table === tableId)
  if (!open.length) return { tone: 'idle', dashed: false, card: null, open: 0 }
  const top = open.reduce((a, b) => ((TONE_RANK[b.variant] ?? 0) > (TONE_RANK[a.variant] ?? 0) ? b : a))
  return {
    tone: TONE_OF[top.variant] ?? 'idle',
    dashed: top.variant === 'bounced' || top.variant === 'reverted',
    card: top,
    open: open.length,
  }
}

/**
 * Where table tiles sit on the floor map, as fractions of the map (grid from /floor x/y).
 * @returns {{ id: string, section: string, seats: number, x: number, y: number, fx: number, fy: number }[]}
 */
export function tableSpots(floor) {
  const tables = floor?.tables ?? []
  if (!tables.length) return []
  const xs = tables.map((t) => t.x)
  const ys = tables.map((t) => t.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const fx = (x) => (x1 === x0 ? 0.5 : 0.15 + (0.7 * (x - x0)) / (x1 - x0))
  const fy = (y) => (y1 === y0 ? 0.5 : 0.36 + (0.38 * (y - y0)) / (y1 - y0))
  return tables.map((t) => ({ ...t, fx: fx(t.x), fy: fy(t.y) }))
}

// ---------- routing log ----------

const LOG_TONE = { queued: 'bone', sent: 'bone', accepted: 'leaf', done: 'leaf', bounced: 'bone', escalated: 'red' }

/** Routing log entries, newest first: who got what, and why. */
export function routingLog(events, floor, limit = 60) {
  const out = []
  for (const e of events) {
    if (!e.type.startsWith('task.') || !e.data?.taskId) continue
    const d = e.data
    const type = e.type.slice(5)
    if (type === 'sent') continue // "delivered" adds nothing a manager acts on
    const who = staffName(floor, d.assignee)
    const what = `${kindLabel(d.kind)} · ${d.table}`
    const title = {
      queued: d.reason === 'created' ? `${what} → ${who}` : `${what} → ${who}`,
      accepted: `${who} accepted ${what}`,
      done: `${who} finished ${what}`,
      bounced: `${who} passed on ${what}`,
      escalated: `${what} escalated from ${who}`,
    }[type]
    if (!title) continue
    out.push({ seq: e.seq, at: ms(e), taskId: d.taskId, table: d.table, tone: LOG_TONE[type], title, reason: logReason(type, d, floor) })
  }
  return out.reverse().slice(0, limit)
}

function logReason(type, d, floor) {
  const r = d.reason ?? ''
  if (type === 'queued' && r === 'created') return 'New task, routed by section and load'
  if (type === 'queued' && r.startsWith('after ')) return `Moved on ${r}`.replace(/ from (\w+)$/, (_, id) => ` from ${staffName(floor, id)}`)
  if (r === 'no accept in time') return 'No accept in time'
  if (r === 'assignee offline') return 'Their glasses were offline'
  if (r.startsWith('task.handoff to ')) return `Handed off to ${staffName(floor, r.slice(16))}`
  if (r.startsWith('manager reroute')) return 'Rerouted from the dashboard'
  if (r === 'task.bounce') return 'Declined on the glasses'
  if (r === 'task.accept') return 'Tapped on the glasses'
  if (r === 'task.done') return 'Tapped done on the glasses'
  if (r.startsWith('not done after')) return `Not done after ${r.slice(15)}`
  return r
}

// ---------- staff, reroute, questions ----------

/** Staff drawer rows: online state, open and finished tasks, average time from /stats. */
export function staffRows(floor, stats, online) {
  const rows = stats?.servers ?? []
  return staffList(floor).map((s) => {
    const st = rows.find((r) => r.id === s.id)
    return {
      id: s.id,
      name: s.name,
      role: s.role,
      sections: s.sections ?? [],
      online: online.has(s.id),
      open: st?.open ?? [],
      done: st?.done ?? 0,
      avgSec: st?.avgSec ?? null,
    }
  })
}

/** Who a reroute should go to: online servers other than the holder, fewest open tasks first. */
export function rerouteTarget(task, floor, stats, online) {
  if (!task || !floor) return null
  const load = new Map((stats?.servers ?? []).map((s) => [s.id, s.open.length]))
  const others = floor.servers.filter((s) => s.id !== task.assignee)
  if (!others.length) return null
  const ranked = [...others].sort(
    (a, b) =>
      Number(online.has(b.id)) - Number(online.has(a.id)) || (load.get(a.id) ?? 0) - (load.get(b.id) ?? 0),
  )
  return ranked[0]
}

/** Diner questions the menu couldn't answer, per table, from clip summaries (order.draft). */
export function openQuestions(orders) {
  const out = []
  for (const o of Object.values(orders ?? {})) {
    if (!o.table || o.status === 'cancelled') continue
    for (const a of o.answers ?? []) if (a.known === false) out.push({ table: o.table, orderId: o.orderId, seat: a.seat, q: a.q })
    for (const u of o.uncertain ?? []) out.push({ table: o.table, orderId: o.orderId, seat: null, q: u })
  }
  return out
}

/** The newest clip summary for a table, if any. */
export function latestClip(orders, table) {
  return Object.values(orders ?? {})
    .filter((o) => o.table === table && (o.summary || o.answers?.length))
    .at(-1) ?? null
}

/** Seconds until the shift ends ("HH:MM" today, or tomorrow if already past). */
export function shiftLeft(nowMs, end = '23:00') {
  const [h, m] = end.split(':').map(Number)
  const d = new Date(nowMs)
  d.setHours(h, m || 0, 0, 0)
  if (d.getTime() <= nowMs) d.setDate(d.getDate() + 1)
  return Math.round((d.getTime() - nowMs) / 1000)
}

/** "02:41:12" */
export function hms(sec) {
  const s = Math.max(0, Math.floor(sec))
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
}
