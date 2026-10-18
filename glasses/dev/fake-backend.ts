// FAKE BACKEND: a stand-in for Coder A's restaurant brain, for glasses development only.
// Speaks the PROPOSED contract in src/contract.ts on ws://localhost:8787/ws and serves a
// fake organizer page on http://localhost:8787/ showing each task's state, the floor and
// open alerts. Two scripts start on the first connect: server tasks, and a manager loop
// (8 tables changing over time, T4 going late, alerts appearing and clearing).
//
//   npx tsx dev/fake-backend.ts
//
// HTTP: GET / (state page), GET /state (JSON), GET /health, POST /reset, POST /add,
//       POST /late?table=T2 (make a table late now)
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { WebSocketServer, type WebSocket, type RawData } from 'ws'
import type { Alert, BackendMessage, GlassesJsonMessage, Task, TableState, TableStatus } from '../src/contract'

const PORT = Number(process.env.FAKE_BACKEND_PORT ?? 8787)
const tag = '[fake-backend]'

const SCRIPT: { delayMs: number; task: Omit<Task, 'state'> }[] = [
  {
    delayMs: 0,
    task: {
      id: 'task-1',
      kind: 'RUN',
      table: 'T12',
      items: [{ qty: 2, dish: 'halibut', seats: [1, 3] }],
      allergies: [{ allergen: 'SHELLFISH', seats: [3] }],
      notes: [],
    },
  },
  {
    delayMs: 1500,
    task: {
      id: 'task-2',
      kind: 'RUN',
      table: 'T4',
      items: [
        { qty: 1, dish: 'duck breast', seats: [2] },
        { qty: 1, dish: 'risotto', seats: [1] },
      ],
      allergies: [],
      notes: ['VIP: anniversary, comp dessert'],
    },
  },
  {
    delayMs: 3000,
    task: {
      id: 'task-3',
      kind: 'CLEAR',
      table: 'T7',
      items: [],
      allergies: [],
      notes: [],
    },
  },
]

const tasks = new Map<string, Task>()
const received: string[] = []
const clients = new Set<WebSocket>()
let timers: ReturnType<typeof setTimeout>[] = []
let scriptStarted = false
let extraCount = 0

function log(...args: unknown[]): void {
  console.log(tag, new Date().toISOString().slice(11, 23), ...args)
}

function send(ws: WebSocket, msg: BackendMessage): void {
  ws.send(JSON.stringify(msg))
  const detail =
    'task' in msg ? `${msg.task.id} ${msg.task.state}` : msg.type === 'alert' ? `${msg.id}${msg.cleared ? ' cleared' : ''}` : ''
  log('->', msg.type, detail)
}

function broadcast(msg: BackendMessage): void {
  for (const ws of clients) send(ws, msg)
}

function assign(task: Task): void {
  tasks.set(task.id, task)
  broadcast({ type: 'task.assigned', task })
}

function startScript(): void {
  if (scriptStarted) return
  scriptStarted = true
  log('script started')
  timers = SCRIPT.map(({ delayMs, task }) => setTimeout(() => assign({ ...task, state: 'assigned' }), delayMs))
}

function reset(): void {
  for (const t of timers) clearTimeout(t)
  timers = []
  tasks.clear()
  received.length = 0
  scriptStarted = false
  extraCount = 0
  stopManager()
  log('reset')
  if (clients.size) {
    startScript()
    startManager()
  }
}

// ---------- manager script ----------

interface FakeTable {
  table: string
  status: TableStatus
  since: number
  x: number
  y: number
  urgency: number
}

/** Floor plan in metres, 4 x 2. */
const FLOOR: Omit<FakeTable, 'since'>[] = [
  { table: 'T1', status: 'eating', x: 0, y: 0, urgency: 0 },
  { table: 'T2', status: 'seated', x: 3, y: 0, urgency: 0 },
  { table: 'T3', status: 'ordered', x: 6, y: 0, urgency: 1 },
  { table: 'T4', status: 'waiting', x: 9, y: 0, urgency: 2 },
  { table: 'T5', status: 'empty', x: 0, y: 4, urgency: 0 },
  { table: 'T6', status: 'ordered', x: 3, y: 4, urgency: 0 },
  { table: 'T7', status: 'seated', x: 6, y: 4, urgency: 1 },
  { table: 'T8', status: 'check', x: 9, y: 4, urgency: 0 },
]
/** Minutes each table has been in its status when the loop starts. */
const START_MIN: Record<string, number> = { T1: 18, T2: 3, T3: 6, T4: 14, T5: 0, T6: 2, T7: 1, T8: 4 }

const MANAGER_LOOP_MS = 60_000
type Step = { atMs: number; tables?: Partial<Record<string, Partial<FakeTable>>>; alerts?: Omit<Alert, 'type'>[] }
const MANAGER_SCRIPT: Step[] = [
  { atMs: 0, alerts: [{ id: 'vip-t7', level: 'info', text: 'VIP seated T7', table: 'T7' }] },
  { atMs: 4000, alerts: [{ id: 'unacked-t3', level: 'warn', text: 'T3 task unacked {elapsed}', table: 'T3', sinceSec: 45 }] },
  {
    atMs: 8000,
    tables: { T4: { urgency: 4 } },
    alerts: [{ id: 'late-t4', level: 'urgent', text: 'T4 waiting {elapsed} on mains', table: 'T4', sinceSec: 14 * 60 + 8 }],
  },
  { atMs: 14000, tables: { T6: { status: 'waiting', urgency: 1 }, T5: { status: 'seated' } } },
  { atMs: 20000, tables: { T3: { status: 'waiting', urgency: 0 } }, alerts: [{ id: 'unacked-t3', level: 'warn', text: '', cleared: true }] },
  { atMs: 30000, tables: { T7: { urgency: 0 } }, alerts: [{ id: 'vip-t7', level: 'info', text: '', cleared: true }] },
  {
    atMs: 40000,
    tables: { T4: { status: 'eating', urgency: 0 }, T8: { status: 'empty' } },
    alerts: [{ id: 'late-t4', level: 'urgent', text: '', cleared: true }],
  },
  { atMs: 50000, tables: { T1: { status: 'check' }, T6: { status: 'eating', urgency: 0 } } },
]

const floor = new Map<string, FakeTable>()
const alerts = new Map<string, Alert>()
let managerTimers: ReturnType<typeof setTimeout>[] = []
let managerLoop: ReturnType<typeof setInterval> | null = null

function tableState(t: FakeTable, now: number): TableState {
  return { table: t.table, status: t.status, sinceSec: Math.round((now - t.since) / 1000), x: t.x, y: t.y, urgency: t.urgency }
}

function floorMsg(): BackendMessage {
  const now = Date.now()
  return { type: 'floor.state', tables: [...floor.values()].map(t => tableState(t, now)) }
}

function alertMsgs(): Alert[] {
  return [...alerts.values()]
}

function setTables(changes: Partial<Record<string, Partial<FakeTable>>>): void {
  const now = Date.now()
  for (const [id, change] of Object.entries(changes)) {
    const t = floor.get(id)
    if (!t || !change) continue
    const statusChanged = change.status !== undefined && change.status !== t.status
    floor.set(id, { ...t, ...change, since: statusChanged ? now : t.since })
  }
  broadcast(floorMsg())
}

const alertStarted = new Map<string, number>()

function setAlert(a: Omit<Alert, 'type'>): void {
  const msg: Alert = { type: 'alert', ...a }
  if (a.cleared) {
    alerts.delete(a.id)
    alertStarted.delete(a.id)
  } else {
    alerts.set(a.id, msg)
    alertStarted.set(a.id, Date.now())
  }
  broadcast(msg)
}

/** An open alert with sinceSec as of now, so a reconnect gets the running timer. */
function currentAlert(a: Alert): Alert {
  if (a.sinceSec === undefined) return a
  const started = alertStarted.get(a.id) ?? Date.now()
  return { ...a, sinceSec: a.sinceSec + Math.round((Date.now() - started) / 1000) }
}

function runManagerCycle(): void {
  const now = Date.now()
  floor.clear()
  for (const t of FLOOR) floor.set(t.table, { ...t, since: now - (START_MIN[t.table] ?? 0) * 60_000 })
  for (const id of alerts.keys()) broadcast({ type: 'alert', id, level: 'info', text: '', cleared: true })
  alerts.clear()
  broadcast(floorMsg())
  log('manager cycle')
  managerTimers = MANAGER_SCRIPT.map(step =>
    setTimeout(() => {
      if (step.tables) setTables(step.tables)
      for (const a of step.alerts ?? []) setAlert(a)
    }, step.atMs),
  )
}

function startManager(): void {
  if (managerLoop) return
  runManagerCycle()
  managerLoop = setInterval(runManagerCycle, MANAGER_LOOP_MS)
}

function stopManager(): void {
  for (const t of managerTimers) clearTimeout(t)
  managerTimers = []
  if (managerLoop) clearInterval(managerLoop)
  managerLoop = null
  floor.clear()
  alerts.clear()
  alertStarted.clear()
}

function makeLate(table: string): boolean {
  if (!floor.has(table)) return false
  const lateMin = 12
  floor.set(table, { ...floor.get(table)!, status: 'waiting', urgency: 4, since: Date.now() - lateMin * 60_000 })
  broadcast(floorMsg())
  setAlert({ id: `late-${table.toLowerCase()}`, level: 'urgent', text: `${table} waiting {elapsed} on mains`, table, sinceSec: lateMin * 60 })
  return true
}

const GLASSES_TYPES: readonly GlassesJsonMessage['type'][] = [
  'task.accept',
  'task.done',
  'task.bounce',
  'capture.start',
  'capture.stop',
  'order.confirm',
  'order.cancel_confirm',
]

function parseGlasses(raw: string): GlassesJsonMessage | null {
  try {
    const v: unknown = JSON.parse(raw)
    if (typeof v !== 'object' || v === null) return null
    const type = (v as { type?: unknown }).type
    return GLASSES_TYPES.includes(type as GlassesJsonMessage['type']) ? (v as GlassesJsonMessage) : null
  } catch {
    return null
  }
}

function setState(taskId: string, state: Task['state']): void {
  const task = tasks.get(taskId)
  if (!task) {
    log('unknown task', taskId)
    return
  }
  const next = { ...task, state }
  tasks.set(taskId, next)
  broadcast({ type: 'task.updated', task: next })
}

function handle(msg: GlassesJsonMessage): void {
  switch (msg.type) {
    case 'task.accept':
      return setState(msg.taskId, 'accepted')
    case 'task.done':
      return setState(msg.taskId, 'done')
    case 'task.bounce':
      return setState(msg.taskId, 'bounced')
    case 'capture.start':
    case 'capture.stop':
    case 'order.confirm':
    case 'order.cancel_confirm':
      return
  }
}

function record(line: string): void {
  received.push(`${new Date().toISOString().slice(11, 19)} ${line}`)
  if (received.length > 200) received.shift()
  log('<-', line)
}

function onMessage(data: RawData, isBinary: boolean): void {
  if (isBinary) {
    const bytes = Array.isArray(data) ? data.reduce((n, b) => n + b.length, 0) : data.byteLength
    record(`capture.audio (binary, ${bytes} bytes)`)
    return
  }
  const raw = data.toString()
  const msg = parseGlasses(raw)
  record(msg ? raw : `INVALID ${raw.slice(0, 200)}`)
  if (msg) handle(msg)
}

const esc = (s: string) => s.replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`)

function page(): string {
  const rows = [...tasks.values()]
    .map(
      t => `<tr class="${t.state}"><td>${esc(t.id)}</td><td>${t.kind}</td><td>${esc(t.table)}</td>
<td>${esc(t.items.map(i => `${i.qty}× ${i.dish} s${i.seats.join('+')}`).join(', '))}</td>
<td>${esc(t.allergies.map(a => `${a.allergen} s${a.seats.join('+')}`).join(', '))}</td>
<td>${esc(t.notes.join('; '))}</td><td class="state" data-task="${esc(t.id)}">${t.state}</td></tr>`,
    )
    .join('\n')
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="1">
<title>FAKE organizer (Floor Sense)</title>
<style>body{font:14px system-ui;margin:24px;background:#111;color:#ddd}table{border-collapse:collapse}
td,th{border:1px solid #444;padding:4px 8px;text-align:left}.accepted .state{color:#ff0}.done .state{color:#3cfa44}
.u4 td{color:#ff0;font-weight:bold}.banner{background:#a40;color:#fff;padding:6px 10px;display:inline-block}pre{background:#000;padding:8px;max-height:300px;overflow:auto}</style>
</head><body><div class="banner">FAKE BACKEND, stand-in for Coder A</div>
<h1>Tasks</h1><p>${clients.size} glasses connected</p>
<table><tr><th>id</th><th>kind</th><th>table</th><th>items</th><th>allergies</th><th>notes</th><th>state</th></tr>
${rows || '<tr><td colspan="7">no tasks yet (waiting for glasses to connect)</td></tr>'}</table>
<h2>Floor</h2><table><tr><th>table</th><th>status</th><th>min</th><th>urgency</th></tr>
${[...floor.values()].map(t => `<tr class="u${t.urgency}"><td>${t.table}</td><td>${t.status}</td><td>${Math.floor((Date.now() - t.since) / 60000)}</td><td>${t.urgency}</td></tr>`).join('\n')}</table>
<h2>Open alerts</h2><ul>${alertMsgs().map(a => `<li>${a.level}: ${esc(a.text)}</li>`).join('') || '<li>none</li>'}</ul>
<h2>Received from glasses</h2><pre>${esc(received.slice(-30).join('\n'))}</pre></body></html>`
}

function json(res: ServerResponse, code: number, body: unknown): void {
  res.writeHead(code, { 'content-type': 'application/json', 'access-control-allow-origin': '*' })
  res.end(JSON.stringify(body))
}

const server = createServer((req: IncomingMessage, res: ServerResponse) => {
  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`)
  if (req.method === 'GET' && url.pathname === '/') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end(page())
  } else if (req.method === 'GET' && url.pathname === '/health') {
    json(res, 200, { ok: true, fake: true })
  } else if (req.method === 'GET' && url.pathname === '/state') {
    json(res, 200, {
      clients: clients.size,
      tasks: [...tasks.values()],
      floor: (floorMsg() as { tables: TableState[] }).tables,
      alerts: alertMsgs().map(currentAlert),
      received,
    })
  } else if (req.method === 'POST' && url.pathname === '/reset') {
    reset()
    json(res, 200, { ok: true })
  } else if (req.method === 'POST' && url.pathname === '/late') {
    const table = url.searchParams.get('table') ?? 'T2'
    json(res, makeLate(table) ? 200 : 404, { ok: floor.has(table), table })
  } else if (req.method === 'POST' && url.pathname === '/add') {
    extraCount += 1
    const task: Task = {
      id: `task-x${extraCount}`,
      kind: 'RUN',
      table: `T${20 + extraCount}`,
      items: [{ qty: 1, dish: 'short rib', seats: [extraCount] }],
      allergies: [],
      notes: [],
      state: 'assigned',
    }
    assign(task)
    json(res, 200, task)
  } else {
    json(res, 404, { error: 'not found' })
  }
})

const wss = new WebSocketServer({ server, path: '/ws' })
wss.on('connection', (ws, req) => {
  clients.add(ws)
  log('glasses connected', req.url, `(${clients.size} total)`)
  for (const task of tasks.values()) if (task.state === 'assigned' || task.state === 'accepted') send(ws, { type: 'task.assigned', task })
  if (floor.size) send(ws, floorMsg())
  for (const a of alertMsgs()) send(ws, currentAlert(a))
  startScript()
  startManager()
  ws.on('message', onMessage)
  ws.on('close', () => {
    clients.delete(ws)
    log('glasses disconnected', `(${clients.size} left)`)
  })
})

server.listen(PORT, () => log(`FAKE backend on http://localhost:${PORT}/ and ws://localhost:${PORT}/ws`))
