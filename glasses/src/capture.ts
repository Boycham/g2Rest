import {
  RebuildPageContainer,
  TextContainerProperty,
  TextContainerUpgrade,
  type EvenAppBridge,
} from '@evenrealities/even_hub_sdk'
import type { OrderClosed, OrderDraft, VoiceState } from './contract'
import { CARD_PADDING, DISPLAY_WIDTH } from './card'
import {
  BAR_HEIGHT,
  BRIGHT,
  DIM,
  DRAFT_HEIGHT,
  closesDraft,
  draftGesture,
  formatDraft,
  type DraftState,
  type Gesture,
} from './draft'
import { MAIN_ID, MAIN_NAME } from './render'
import type { BackendSocket } from './socket'
import { log } from './log'

// The draft screen of the server role: sends a clipped minute (capture.start mode=clip, its
// frames, capture.stop), then shows the order.draft the backend makes of it in two text
// containers (order, pending bar). The mic and its rolling buffer belong to ServerHud.

const BAR_ID = 2
/** No draft out of `processing` for this clip within this time means VOICE OFFLINE. */
const CLIP_TIMEOUT_MS = 30_000

declare global {
  interface Window {
    /** Dev measurement: swipe down -> draft from that clip shown on the glasses, ms. */
    __fsLatency?: number[]
  }
}

function container(id: number, y: number, height: number, content: string, color: number, capture: 0 | 1) {
  return new TextContainerProperty({
    xPosition: 0,
    yPosition: y,
    width: DISPLAY_WIDTH,
    height,
    borderWidth: 0,
    paddingLength: CARD_PADDING,
    containerID: id,
    containerName: id === MAIN_ID ? MAIN_NAME : 'bar',
    content: content || ' ',
    textColor: color,
    isEventCapture: capture,
  })
}

export class CaptureScreen {
  private draft: OrderDraft | null = null
  private clipId: string | null = null
  private voice: VoiceState = 'idle'
  private hint: string | null = null
  private online = false
  private active = false
  private timer: ReturnType<typeof setTimeout> | null = null
  private clipAt: number | null = null
  private shown = ''
  private writing = false
  private dirty = false

  constructor(
    private readonly bridge: EvenAppBridge,
    private readonly socket: BackendSocket,
    private readonly onChange: () => void,
  ) {}

  get processing(): boolean {
    return this.voice === 'processing'
  }

  private state(): DraftState {
    return { draft: this.draft, voice: this.voice, online: this.online, hint: this.hint }
  }

  /** Switch to this screen (one rebuild), then every later change is an in-place upgrade. */
  async enter(): Promise<void> {
    this.active = true
    const v = formatDraft(this.state())
    this.shown = JSON.stringify(v)
    const page = new RebuildPageContainer({
      containerTotalNum: 2,
      textObject: [
        container(MAIN_ID, 0, DRAFT_HEIGHT, v.main, v.highlight ? DIM : BRIGHT, 1),
        container(BAR_ID, DRAFT_HEIGHT, BAR_HEIGHT, v.bar, BRIGHT, 0),
      ],
    })
    const t0 = performance.now()
    const ok = await this.bridge.rebuildPageContainer(page)
    log('rebuild draft', ok, `${(performance.now() - t0).toFixed(1)} ms`)
  }

  /** Leaving the screen keeps the draft; the backend may still answer the last clip. */
  leave(): void {
    this.active = false
  }

  /**
   * Send the clipped minute. Frames go out back to back (the socket buffers them); nothing
   * is kept here once they are sent. Returns false if there was nothing to send.
   */
  sendClip(frames: readonly ArrayBuffer[], table?: string): boolean {
    if (!this.online) {
      this.hint = 'offline: clip not sent'
      this.changed()
      return false
    }
    if (!frames.length) {
      this.hint = 'mic off: nothing recorded'
      this.changed()
      return false
    }
    const id = `clip-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    this.clipId = id
    this.clipAt = performance.now()
    this.voice = 'processing'
    this.hint = null
    this.socket.send({ type: 'capture.start', captureId: id, mode: 'clip', ...(table ? { table } : {}) })
    for (const f of frames) this.socket.sendAudio(f)
    this.socket.send({ type: 'capture.stop', captureId: id })
    log('clip sent', id, `${(frames.length / 10).toFixed(1)} s`, table ?? 'no table')
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      if (this.clipId === id && this.voice === 'processing') this.offline('no draft for the clip')
    }, CLIP_TIMEOUT_MS)
    this.changed()
    return true
  }

  private offline(why: string): void {
    log('VOICE OFFLINE:', why)
    this.voice = 'offline'
    this.changed()
  }

  onDraft(msg: OrderDraft): void {
    if (msg.orderId) this.draft = msg
    if (msg.voice === 'offline') return this.offline(msg.notice ?? 'relay reported offline')
    if (msg.captureId === this.clipId && msg.voice) this.voice = msg.voice
    if (!this.processing && this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    this.changed()
  }

  /** The send / cancel tap landed: draft dropped. True if it was the draft on screen. */
  onClosed(msg: OrderClosed): boolean {
    if (!closesDraft(this.draft, msg.orderId)) return false
    log('order closed', msg.orderId, msg.status)
    this.draft = null
    this.clipId = null
    this.voice = 'idle'
    this.changed()
    return true
  }

  setOnline(online: boolean): void {
    this.online = online
    if (!online && this.processing) this.offline('backend socket offline')
    else this.changed()
  }

  /** 'clip': the caller sends a new last minute; 'back': return to the card. */
  gesture(g: Gesture): 'back' | 'clip' | 'none' {
    const a = draftGesture(g, this.state())
    if (a.send) this.socket.send(a.send)
    if (a.then === 'clip' && this.voice === 'offline') this.voice = 'idle'
    return a.then
  }

  /** A transient line on the draft (voice command feedback). */
  setHint(text: string | null): void {
    this.hint = text
    this.changed()
  }

  private changed(): void {
    this.onChange()
    void this.render()
  }

  /** Writes are serialized and coalesced so a burst of drafts ends on the latest one. */
  private async render(): Promise<void> {
    if (!this.active) return
    if (this.writing) {
      this.dirty = true
      return
    }
    this.writing = true
    try {
      do {
        this.dirty = false
        const v = formatDraft(this.state())
        const key = JSON.stringify(v)
        if (key === this.shown) continue
        const prev = JSON.parse(this.shown || '{}') as Partial<typeof v>
        const t0 = performance.now()
        if (prev.main !== v.main || prev.highlight !== v.highlight) {
          await this.bridge.textContainerUpgrade(
            new TextContainerUpgrade({
              containerID: MAIN_ID,
              containerName: MAIN_NAME,
              content: v.main || ' ',
              textColor: v.highlight ? DIM : BRIGHT,
            }),
          )
        }
        if (prev.bar !== v.bar) {
          await this.bridge.textContainerUpgrade(
            new TextContainerUpgrade({ containerID: BAR_ID, containerName: 'bar', content: v.bar || ' ', textColor: BRIGHT }),
          )
        }
        this.shown = key
        const t1 = performance.now()
        log('draft upgrade', `${(t1 - t0).toFixed(1)} ms`, JSON.stringify(v.main), JSON.stringify(v.bar))
        if (this.clipAt !== null && !this.processing && this.draft?.captureId === this.clipId) {
          const ms = Math.round(t1 - this.clipAt)
          ;(window.__fsLatency ??= []).push(ms)
          log('latency swipe down -> draft on glasses', `${ms} ms`)
          this.clipAt = null
        }
      } while (this.dirty && this.active)
    } finally {
      this.writing = false
    }
  }
}
