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
import { PROCESSING, SUMMARY, Ticker, dots } from './busy'
import type { BackendSocket } from './socket'
import { log } from './log'

// The draft screen of the server role: sends a clipped minute (capture.start mode=clip, its
// frames, capture.stop), then shows the order.draft the backend makes of it in two text
// containers (order, pending bar). The mic and its rolling buffer belong to ServerHud.

const BAR_ID = 2
/** No draft out of `processing` for this clip within this time means VOICE OFFLINE. */
const CLIP_TIMEOUT_MS = 30_000
/** After the order card, `summary...` waits this long for the talk agent, then just goes. */
const TALK_WAIT_MS = 15_000

declare global {
  interface Window {
    /** Dev measurement: swipe back -> draft from that clip shown on the glasses, ms. */
    __fsLatency?: number[]
    /** Swipe -> the clip's summary/answers on the lens (they follow the order card). */
    __fsTalkLatency?: number[]
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
  private talkAt: number | null = null
  private page = 0
  private shown = ''
  private writing = false
  private dirty = false
  private talkUntil: number | null = null
  private mapping = false
  private readonly ticker = new Ticker(() => this.tick())

  constructor(
    private readonly bridge: EvenAppBridge,
    private readonly socket: BackendSocket,
    private readonly onChange: () => void,
  ) {}

  get processing(): boolean {
    return this.voice === 'processing'
  }

  private state(): DraftState {
    return { draft: this.draft, voice: this.voice, online: this.online, hint: this.hint, page: this.page, busy: this.busy() }
  }

  /** What Verity is still working on, or null when nothing is. */
  private busy(): string | null {
    if (this.processing || this.mapping) return dots(PROCESSING, this.ticker.tick)
    return this.talkPending() ? dots(SUMMARY, this.ticker.tick) : null
  }

  private talkPending(): boolean {
    const d = this.draft
    if (this.talkUntil === null || this.voice === 'offline' || !d || d.captureId !== this.clipId) return false
    if (d.summary || d.answers?.length || (d.status ?? 'draft') !== 'draft') return false
    return performance.now() < this.talkUntil
  }

  /** One beat: only the bar's text changes, so render() upgrades that one container. */
  private tick(): void {
    this.syncTicker()
    void this.render()
  }

  private syncTicker(): boolean {
    const on = this.active && this.busy() !== null
    this.ticker.set(on)
    return on
  }

  /** Gemini is mapping unknown "verity" words (voice.mapping until voice.command / voice.unknown). */
  setMapping(on: boolean): void {
    if (this.mapping === on) return
    this.mapping = on
    this.changed()
  }

  /** Switch to this screen (one rebuild), then every later change is an in-place upgrade. */
  async enter(): Promise<void> {
    this.active = true
    this.syncTicker()
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
    this.ticker.set(false)
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
    this.talkAt = this.clipAt
    this.talkUntil = null
    this.page = 0
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
    if (msg.captureId !== this.draft?.captureId) this.page = 0
    if (msg.orderId) this.draft = msg
    if (msg.voice === 'offline') return this.offline(msg.notice ?? 'relay reported offline')
    if (msg.captureId === this.clipId && msg.voice) this.voice = msg.voice
    if (!this.processing && this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    if (msg.captureId === this.clipId && !this.processing && this.talkUntil === null) this.talkUntil = performance.now() + TALK_WAIT_MS
    this.changed()
  }

  /** The send / cancel tap landed: draft dropped. True if it was the draft on screen. */
  onClosed(msg: OrderClosed): boolean {
    if (!closesDraft(this.draft, msg.orderId)) return false
    log('order closed', msg.orderId, msg.status)
    this.draft = null
    this.page = 0
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

  /** 'clip': the caller sends a new last 2 minutes; 'back': return to the card. */
  gesture(g: Gesture): 'back' | 'clip' | 'none' {
    const a = draftGesture(g, this.state())
    if (a.send) this.socket.send(a.send)
    if (a.then === 'clip' && this.voice === 'offline') this.voice = 'idle'
    if (a.then === 'page') {
      this.page++
      this.changed()
      return 'none'
    }
    return a.then
  }

  /** A transient line on the draft (voice command feedback). */
  setHint(text: string | null): void {
    this.hint = text
    this.changed()
  }

  private changed(): void {
    this.onChange()
    this.syncTicker()
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
        if (prev.main === v.main && this.ticker.running) log('busy upgrade', `${(t1 - t0).toFixed(1)} ms`, JSON.stringify(v.bar))
        else log('draft upgrade', `${(t1 - t0).toFixed(1)} ms`, JSON.stringify(v.main), JSON.stringify(v.bar))
        if (this.clipAt !== null && !this.processing && this.draft?.captureId === this.clipId) {
          const ms = Math.round(t1 - this.clipAt)
          ;(window.__fsLatency ??= []).push(ms)
          log('latency swipe back -> draft on glasses', `${ms} ms`)
          this.clipAt = null
        }
        if (this.talkAt !== null && this.draft?.captureId === this.clipId && (this.draft.summary || this.draft.answers?.length)) {
          const ms = Math.round(t1 - this.talkAt)
          ;(window.__fsTalkLatency ??= []).push(ms)
          log('latency swipe back -> summary and answers on glasses', `${ms} ms`)
          this.talkAt = null
        }
      } while (this.dirty && this.active)
    } finally {
      this.writing = false
    }
  }
}
