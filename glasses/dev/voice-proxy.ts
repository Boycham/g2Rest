// FAKE BACKEND part 2: forwards the glasses' capture.* / order.* traffic to the Python
// voice relay (backend/voice/relay.py) so the glasses keep one socket, and keeps a fake
// kitchen ticket list of every order the relay reports as sent.
import WebSocket, { type RawData } from 'ws'
import type { OrderDraft } from '../src/contract'

const RELAY_URL = process.env.VOICE_RELAY_URL ?? 'ws://localhost:8790/ws'
const CONNECT_TIMEOUT_MS = 3000
const OFFLINE_NOTICE = 'voice relay unreachable'

export interface KitchenTicket {
  at: string
  draft: OrderDraft
}

export const kitchen: KitchenTicket[] = []

export const VOICE_TYPES = ['capture.start', 'capture.stop', 'order.confirm', 'order.cancel_confirm', 'order.reject']

/** One per glasses connection. `toGlasses` writes a JSON text frame back to the glasses. */
export class VoiceProxy {
  private ws: WebSocket | null = null
  private queue: (string | Buffer)[] = []
  private lastDraft: OrderDraft | null = null
  private captureId = ''
  private closed = false

  constructor(
    private readonly toGlasses: (raw: string) => void,
    private readonly log: (...args: unknown[]) => void,
  ) {}

  forward(data: string | Buffer): void {
    if (typeof data === 'string') {
      const m = /"captureId"\s*:\s*"([^"]+)"/.exec(data)
      if (m && data.includes('capture.start')) this.captureId = m[1]
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data)
      return
    }
    if (typeof data === 'string') this.queue.push(data)
    else if (this.queue.length < 50) this.queue.push(data)
    this.connect()
  }

  private connect(): void {
    if (this.ws || this.closed) return
    const ws = new WebSocket(RELAY_URL)
    this.ws = ws
    const timer = setTimeout(() => {
      this.log('voice relay connect timeout')
      ws.terminate()
    }, CONNECT_TIMEOUT_MS)
    ws.on('open', () => {
      clearTimeout(timer)
      this.log('voice relay connected', RELAY_URL)
      for (const d of this.queue) ws.send(d)
      this.queue = []
    })
    ws.on('message', (data: RawData) => this.fromRelay(data.toString()))
    ws.on('error', err => this.log('voice relay error', err.message))
    ws.on('close', () => {
      clearTimeout(timer)
      if (this.ws === ws) this.ws = null
      this.queue = []
      if (!this.closed) this.offline()
    })
  }

  private fromRelay(raw: string): void {
    this.toGlasses(raw)
    try {
      const msg = JSON.parse(raw) as OrderDraft
      if (msg.type !== 'order.draft') return
      this.lastDraft = msg
      if (msg.status === 'sent' && !kitchen.some(t => t.draft.orderId === msg.orderId)) {
        kitchen.push({ at: new Date().toISOString().slice(11, 19), draft: msg })
        this.log('KITCHEN ticket', msg.table, msg.lines.map(l => `s${l.seat} ${l.dish}`).join(', '))
      }
    } catch {
      this.log('relay sent invalid JSON', raw.slice(0, 200))
    }
  }

  /** Relay down: tell the glasses with the last draft they had, marked offline. */
  private offline(): void {
    this.log('VOICE OFFLINE:', OFFLINE_NOTICE)
    const base: OrderDraft = this.lastDraft ?? {
      type: 'order.draft',
      orderId: '',
      captureId: this.captureId,
      table: null,
      lines: [],
      allergies: [],
    }
    this.toGlasses(JSON.stringify({ ...base, voice: 'offline', notice: OFFLINE_NOTICE }))
  }

  close(): void {
    this.closed = true
    this.ws?.close()
  }
}

const esc = (s: string) => s.replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`)

export function kitchenPage(): string {
  const tickets = kitchen
    .slice()
    .reverse()
    .map(({ at, draft }) => {
      const allergies = (draft.allergies ?? []).map(a => `<div class="allergy">! ${esc(a.allergen)} s${a.seats.join('+')}</div>`).join('')
      const lines = draft.lines
        .map(l => {
          const alt = [...l.alterations.map(a => `–${a}`), ...l.flagged.map(f => `?${f}`)].join(' ')
          return `<li>s${l.seat} ${l.qty > 1 ? `${l.qty}× ` : ''}${esc(l.dish)} <span class="alt">${esc(alt)}</span></li>`
        })
        .join('')
      return `<div class="ticket" data-order="${esc(draft.orderId)}"><h2>${esc(draft.table ?? '?')} <small>${at} · ${esc(draft.orderId)}</small></h2>${allergies}<ul>${lines}</ul></div>`
    })
    .join('\n')
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="1">
<title>FAKE kitchen (Floor Sense)</title>
<style>body{font:16px system-ui;margin:24px;background:#111;color:#ddd}.ticket{background:#f4f1e6;color:#111;padding:12px 16px;margin:0 0 16px;width:360px;font-family:monospace}
h2{margin:0 0 8px}small{font-weight:normal;color:#555}.allergy{background:#c00;color:#fff;padding:2px 6px;font-weight:bold}.alt{color:#333}
.banner{background:#a40;color:#fff;padding:6px 10px;display:inline-block}</style></head><body>
<div class="banner">FAKE KITCHEN, stand-in for Coder A</div><h1>Kitchen tickets</h1>
${tickets || '<p>no orders sent yet</p>'}</body></html>`
}
