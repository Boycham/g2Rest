import type { BackendMessage, GlassesJsonMessage } from './contract'
import { parseBackendMessage } from './parse'
import { redactToken } from './backend-url'
import { log } from './log'

export type SocketStatus = 'connecting' | 'online' | 'offline'

export interface SocketHandlers {
  onMessage(msg: BackendMessage): void
  onStatus(status: SocketStatus): void
  /** A JSON frame went out (breadcrumbs). */
  onSent?(msg: GlassesJsonMessage): void
  onClose?(code: number): void
}

const CONNECT_TIMEOUT_MS = 5000
const BACKOFF_MIN_MS = 500
const BACKOFF_MAX_MS = 10000
const OUTBOX_MAX = 50

/**
 * One WebSocket to the backend with reconnect and backoff. Gestures made while offline
 * wait in a small outbox and are flushed in order on reconnect.
 */
export class BackendSocket {
  private ws: WebSocket | null = null
  private status: SocketStatus = 'offline'
  private backoff = BACKOFF_MIN_MS
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private connectTimer: ReturnType<typeof setTimeout> | null = null
  private outbox: GlassesJsonMessage[] = []

  constructor(
    private url: string,
    private readonly handlers: SocketHandlers,
  ) {}

  get online(): boolean {
    return this.status === 'online'
  }

  connect(): void {
    this.clearTimers()
    this.teardown()
    this.setStatus('connecting')
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
      if (this.connectTimer) clearTimeout(this.connectTimer)
      this.backoff = BACKOFF_MIN_MS
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
      this.handlers.onClose?.(ev.code)
      this.ws = null
      this.scheduleRetry()
    }
    ws.onerror = () => log('ws error')
  }

  get currentUrl(): string {
    return this.url
  }

  /** Role switch: the backend routes by the role/staff on the socket, so dial the new URL now. */
  redial(url: string): void {
    this.url = url
    this.reconnectNow()
  }

  /** Drop the current socket and dial again now (e.g. on the foreground event). */
  reconnectNow(): void {
    this.backoff = BACKOFF_MIN_MS
    this.connect()
  }

  send(msg: GlassesJsonMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
      log('sent', msg.type)
      this.handlers.onSent?.(msg)
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
    const delay = this.backoff
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS)
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
