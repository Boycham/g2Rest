import type { BackendMessage, GlassesJsonMessage } from './contract'
import { parseBackendMessage } from './parse'
import { redactToken } from './backend-url'
import { log } from './log'

export type SocketStatus = 'connecting' | 'online' | 'offline'

export interface SocketHandlers {
  onMessage(msg: BackendMessage): void
  onStatus(status: SocketStatus): void
}

const CONNECT_TIMEOUT_MS = 5000
const BACKOFF_MIN_MS = 500
const BACKOFF_MAX_MS = 10000
const OUTBOX_MAX = 50

/**
 * Wait before reconnect attempt `attempt` (0-based): doubling from 500 ms, capped at 10 s, and
 * jittered to between half and all of that so glasses don't all redial a restarted backend at once.
 */
export function retryDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(BACKOFF_MIN_MS * 2 ** attempt, BACKOFF_MAX_MS)
  return Math.round(base / 2 + (random() * base) / 2)
}

/**
 * One WebSocket to the backend with reconnect and backoff. Every dial asks `urlFor` for the URL,
 * so a retry after a backend restart carries the current role and staff, not the ones at startup.
 * Gestures made while offline wait in a small outbox and are flushed in order on reconnect.
 */
export class BackendSocket {
  private ws: WebSocket | null = null
  private status: SocketStatus = 'offline'
  private attempt = 0
  private url = ''
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private connectTimer: ReturnType<typeof setTimeout> | null = null
  private outbox: GlassesJsonMessage[] = []

  constructor(
    private readonly urlFor: () => string,
    private readonly handlers: SocketHandlers,
    private readonly random: () => number = Math.random,
  ) {}

  get online(): boolean {
    return this.status === 'online'
  }

  connect(): void {
    this.clearTimers()
    this.teardown()
    this.setStatus('connecting')
    this.url = this.urlFor()
    log('ws connecting', redactToken(this.url))
    let ws: WebSocket
    try {
      ws = new WebSocket(this.url)
    } catch (err) {
      log('ws construct failed', String(err))
      this.scheduleRetry()
      return
    }
    ws.binaryType = 'arraybuffer'
    this.ws = ws
    this.connectTimer = setTimeout(() => {
      log('ws connect timeout')
      ws.close()
    }, CONNECT_TIMEOUT_MS)

    ws.onopen = () => {
      if (this.ws !== ws) return
      this.clearTimers()
      this.attempt = 0
      this.setStatus('online')
      log('ws open; flushing', this.outbox.length)
      const pending = this.outbox
      this.outbox = []
      for (const msg of pending) this.send(msg)
    }
    ws.onmessage = ev => {
      if (this.ws !== ws || typeof ev.data !== 'string') return
      const msg = parseBackendMessage(ev.data)
      if (!msg) {
        log('ws dropped invalid message', ev.data.slice(0, 200))
        return
      }
      this.handlers.onMessage(msg)
    }
    ws.onclose = ev => {
      if (this.ws !== ws) return
      log('ws closed', ev.code)
      this.ws = null
      this.clearTimers()
      this.scheduleRetry()
    }
    ws.onerror = () => log('ws error')
  }

  get currentUrl(): string {
    return this.url
  }

  /** Drop the current socket and dial again now: on a role switch and on the foreground event. */
  reconnectNow(): void {
    this.attempt = 0
    this.connect()
  }

  send(msg: GlassesJsonMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
      log('sent', msg.type)
      return
    }
    this.outbox.push(msg)
    if (this.outbox.length > OUTBOX_MAX) this.outbox.shift()
    log('queued while offline', msg.type)
  }

  /** `capture.audio`: raw PCM frames go out as binary and are not buffered offline. */
  sendAudio(frame: ArrayBuffer): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(frame)
  }

  private scheduleRetry(): void {
    this.setStatus('offline')
    if (this.retryTimer) return
    const delay = retryDelay(this.attempt++, this.random)
    log('ws retry in ms', delay)
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.connect()
    }, delay)
  }

  private teardown(): void {
    const ws = this.ws
    this.ws = null
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null
      ws.close()
    }
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer)
    if (this.connectTimer) clearTimeout(this.connectTimer)
    this.retryTimer = this.connectTimer = null
  }

  private setStatus(status: SocketStatus): void {
    if (status === this.status) return
    this.status = status
    this.handlers.onStatus(status)
  }
}
