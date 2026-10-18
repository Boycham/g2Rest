import {
  RebuildPageContainer,
  TextContainerProperty,
  TextContainerUpgrade,
  type EvenAppBridge,
} from '@evenrealities/even_hub_sdk'
import type { OrderDraft, VoiceState } from './contract'
import { CARD_PADDING, DISPLAY_WIDTH } from './card'
import { debugFixtures, streamFixture, type DebugStream } from './debug-pcm'
import { BAR_HEIGHT, BRIGHT, DIM, DRAFT_HEIGHT, draftGesture, formatDraft, type DraftState, type Gesture } from './draft'
import { FrameChunker, Mic, toBytes } from './mic'
import { MAIN_ID, MAIN_NAME } from './render'
import type { BackendSocket } from './socket'
import { log } from './log'

// The capture / draft screen of the server role: owns the mic, the capture id, the latest
// order.draft and the two text containers (order, pending bar). The mic is on only
// between capture.start and capture.stop.

const BAR_ID = 2
/** No `voice: listening` draft for this capture within this time means VOICE OFFLINE. */
const START_TIMEOUT_MS = 10_000

declare global {
  interface Window {
    /** Dev measurement: end of speech -> draft shown on the glasses, ms. */
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
  private captureId: string | null = null
  private voice: VoiceState = 'idle'
  private online = false
  private active = false
  private readonly mic: Mic
  private readonly chunker = new FrameChunker()
  private readonly fixtures = debugFixtures()
  private nextFixture = 0
  private debug: DebugStream | null = null
  private startTimer: ReturnType<typeof setTimeout> | null = null
  private speechEndAt: number | null = null
  private shown = ''
  private writing = false
  private dirty = false

  constructor(
    private readonly bridge: EvenAppBridge,
    private readonly socket: BackendSocket,
    private readonly onChange: () => void,
  ) {
    this.mic = new Mic(bridge)
    if (this.fixtures.length) log('DEBUG PCM path on:', this.fixtures.join(','))
  }

  get capturing(): boolean {
    return this.captureId !== null
  }

  private state(): DraftState {
    return { draft: this.draft, capturing: this.capturing, voice: this.voice, online: this.online }
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

  /** Leaving the screen always turns the mic off; the draft is kept. */
  leave(): void {
    this.stop()
    this.active = false
  }

  start(): void {
    if (this.capturing) return
    const id = `cap-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    this.captureId = id
    this.voice = 'connecting'
    this.chunker.reset()
    this.socket.send({ type: 'capture.start', captureId: id })
    this.startTimer = setTimeout(() => {
      if (this.captureId === id && this.voice === 'connecting') this.offline('no answer from the voice relay')
    }, START_TIMEOUT_MS)
    const fixture = this.fixtures[this.nextFixture]
    if (fixture) {
      this.nextFixture = (this.nextFixture + 1) % this.fixtures.length
      this.debug = streamFixture(
        fixture,
        frame => this.sendFrame(frame),
        t => (this.speechEndAt = t),
      )
    } else {
      void this.mic.set(true).then(ok => {
        if (!ok && this.captureId === id) this.offline('mic did not open')
      })
    }
    this.changed()
  }

  stop(): void {
    if (this.startTimer) clearTimeout(this.startTimer)
    this.startTimer = null
    this.debug?.stop()
    this.debug = null
    void this.mic.set(false)
    if (this.captureId) this.socket.send({ type: 'capture.stop', captureId: this.captureId })
    this.captureId = null
    if (this.voice !== 'offline') this.voice = 'idle'
    this.changed()
  }

  private offline(why: string): void {
    log('VOICE OFFLINE:', why)
    this.stop()
    this.voice = 'offline'
    this.changed()
  }

  private sendFrame(frame: ArrayBuffer): void {
    if (this.capturing) this.socket.sendAudio(frame)
  }

  /** SDK audioEvent: only forwarded while capturing from the real mic. */
  onAudio(pcm: unknown): void {
    if (!this.capturing || this.debug || !this.mic.isOpen) return
    const bytes = toBytes(pcm)
    if (!bytes) return
    for (const frame of this.chunker.push(bytes)) this.sendFrame(frame)
  }

  onDraft(msg: OrderDraft): void {
    if (msg.orderId) this.draft = msg
    const voice = msg.voice ?? this.voice
    if (msg.captureId === this.captureId && voice !== 'offline') {
      this.voice = voice
      if (voice === 'listening' && this.startTimer) {
        clearTimeout(this.startTimer)
        this.startTimer = null
      }
    }
    if (voice === 'offline') this.offline(msg.notice ?? 'relay reported offline')
    else this.changed()
  }

  setOnline(online: boolean): void {
    this.online = online
    if (!online && this.capturing) this.offline('backend socket offline')
    else this.changed()
  }

  gesture(g: Gesture): 'back' | 'none' {
    const a = draftGesture(g, this.state())
    if (a.send) this.socket.send(a.send)
    if (a.then === 'stop') this.stop()
    if (a.then === 'listen') {
      if (this.voice === 'offline') this.voice = 'idle'
      this.start()
    }
    return a.then === 'back' ? 'back' : 'none'
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
        if (this.speechEndAt !== null && prev.main !== undefined && (prev.main !== v.main || prev.bar !== v.bar)) {
          const ms = Math.round(t1 - this.speechEndAt)
          ;(window.__fsLatency ??= []).push(ms)
          log('latency end of speech -> draft on glasses', `${ms} ms`)
          this.speechEndAt = null
        }
      } while (this.dirty && this.active)
    } finally {
      this.writing = false
    }
  }
}
