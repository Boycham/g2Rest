// FAKE BACKEND: a stand-in for Coder A's restaurant brain, for glasses development only.
// Speaks the PROPOSED contract in src/contract.ts on ws://localhost:8787/ws and serves a
// fake organizer page on http://localhost:8787/ showing each task's state.
//
//   npx tsx dev/fake-backend.ts
//
// capture.* / order.* are proxied to the voice relay (dev/voice-proxy.ts).
// HTTP: GET / (state page), GET /kitchen, GET /state (JSON), GET /health, POST /reset, POST /add
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { WebSocketServer, type WebSocket, type RawData } from 'ws'
import type { BackendMessage, GlassesJsonMessage, Task } from '../src/contract'
import { kitchen, kitchenPage, VOICE_TYPES, VoiceProxy } from './voice-proxy'

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
  log('->', msg.type, 'task' in msg ? `${msg.task.id} ${msg.task.state}` : '')
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
  // Tasks due now are created synchronously, before this connection's first message
  // (e.g. a flushed offline task.accept) is handled.
  for (const { delayMs, task } of SCRIPT) {
    if (delayMs <= 0) assign({ ...task, state: 'assigned' })
    else timers.push(setTimeout(() => assign({ ...task, state: 'assigned' }), delayMs))
  }
}

function reset(): void {
  for (const t of timers) clearTimeout(t)
  timers = []
  tasks.clear()
  received.length = 0
  scriptStarted = false
  extraCount = 0
  log('reset')
  if (clients.size) startScript()
}

const GLASSES_TYPES: readonly GlassesJsonMessage['type'][] = [
  'task.accept',
  'task.done',
  'task.bounce',
  'capture.start',
  'capture.stop',
  'order.confirm',
  'order.cancel_confirm',
  'order.reject',
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
    case 'order.reject':
      return
  }
}

function record(line: string): void {
  received.push(`${new Date().toISOString().slice(11, 19)} ${line}`)
  if (received.length > 200) received.shift()
  log('<-', line)
}

let audioFrames = 0

function onMessage(voice: VoiceProxy, data: RawData, isBinary: boolean): void {
  if (isBinary) {
    const frame = Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data as ArrayBuffer)
    // One log line per second of audio, not per 100 ms frame.
    if (audioFrames++ % 10 === 0) record(`capture.audio (binary, ${frame.byteLength} bytes) #${audioFrames}`)
    voice.forward(frame)
    return
  }
  const raw = data.toString()
  const msg = parseGlasses(raw)
  record(msg ? raw : `INVALID ${raw.slice(0, 200)}`)
  if (msg && VOICE_TYPES.includes(msg.type)) {
    if (msg.type === 'capture.start') audioFrames = 0
    voice.forward(raw)
  } else if (msg) handle(msg)
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
.banner{background:#a40;color:#fff;padding:6px 10px;display:inline-block}pre{background:#000;padding:8px;max-height:300px;overflow:auto}</style>
</head><body><div class="banner">FAKE BACKEND, stand-in for Coder A</div>
<p><a href="/kitchen" style="color:#3cfa44">kitchen tickets (${kitchen.length})</a></p><h1>Tasks</h1><p>${clients.size} glasses connected</p>
<table><tr><th>id</th><th>kind</th><th>table</th><th>items</th><th>allergies</th><th>notes</th><th>state</th></tr>
${rows || '<tr><td colspan="7">no tasks yet (waiting for glasses to connect)</td></tr>'}</table>
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
  } else if (req.method === 'GET' && url.pathname === '/kitchen') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end(kitchenPage())
  } else if (req.method === 'GET' && url.pathname === '/health') {
    json(res, 200, { ok: true, fake: true })
  } else if (req.method === 'GET' && url.pathname === '/state') {
    json(res, 200, { clients: clients.size, tasks: [...tasks.values()], received, kitchen })
  } else if (req.method === 'POST' && url.pathname === '/reset') {
    reset()
    json(res, 200, { ok: true })
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
  startScript()
  const voice = new VoiceProxy(raw => ws.readyState === ws.OPEN && ws.send(raw), log)
  ws.on('message', (data, isBinary) => onMessage(voice, data, isBinary))
  ws.on('close', () => {
    voice.close()
    clients.delete(ws)
    log('glasses disconnected', `(${clients.size} left)`)
  })
})

server.listen(PORT, () => log(`FAKE backend on http://localhost:${PORT}/ and ws://localhost:${PORT}/ws`))
