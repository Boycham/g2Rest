import { RebuildPageContainer } from '@evenrealities/even_hub_sdk'
import type { BackendMessage } from './contract'
import { formatCard, formatQueue } from './card'
import type { Hud, HudContext, PageSpec } from './hud'
import { MAIN_ID, MAIN_NAME, TextSlot, fullTextPage } from './render'
import { saveQueue } from './storage'
import { tap, upsertTask, type Queue } from './tasks'
import { log } from './log'

type Screen = 'card' | 'queue' | 'listening'

const LISTENING_TEXT = 'Listening… (swipe down to stop)'

function newCaptureId(): string {
  return `cap-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** The server HUD: one task card, the queue, and order capture. */
export class ServerHud implements Hud {
  readonly role = 'server'
  queue: Queue
  captureId: string | null = null
  private current: Screen = 'card'
  private readonly card: TextSlot

  constructor(
    private readonly ctx: HudContext,
    restored: Queue,
  ) {
    this.queue = restored
    this.card = new TextSlot(ctx.bridge, MAIN_ID, MAIN_NAME, 'card', () =>
      ctx.active() && this.current === 'card' ? this.currentCard() : null,
    )
  }

  screen(): Screen {
    return this.current
  }

  private currentCard() {
    return formatCard(this.queue, { offline: this.ctx.status() !== 'online' })
  }

  startPage(): PageSpec {
    this.current = 'card'
    const card = this.currentCard()
    this.card.shown(card)
    return { containerTotalNum: 1, textObject: [fullTextPage(card.text, card.brightness)] }
  }

  enter(): Promise<void> {
    return this.showScreen('card')
  }

  leave(): void {
    this.stopCapture()
    this.current = 'card'
  }

  private async showScreen(next: Screen): Promise<void> {
    this.current = next
    const card = this.currentCard()
    const text = next === 'listening' ? LISTENING_TEXT : next === 'queue' ? formatQueue(this.queue) : card.text
    const brightness = next === 'card' ? card.brightness : 4
    const page = new RebuildPageContainer({ containerTotalNum: 1, textObject: [fullTextPage(text, brightness)] })
    if (next === 'card') this.card.shown(card)
    const t0 = performance.now()
    const ok = await this.ctx.bridge.rebuildPageContainer(page)
    log('rebuild', next, ok, `${(performance.now() - t0).toFixed(1)} ms`)
    this.ctx.syncPhone()
  }

  private changed(): void {
    void saveQueue(this.ctx.bridge, this.queue)
    void this.card.render()
    this.ctx.syncPhone()
  }

  onMessage(msg: BackendMessage): void {
    if (msg.type !== 'task.assigned' && msg.type !== 'task.updated') return
    log('<-', msg.type, msg.task.id, msg.task.state)
    this.queue = upsertTask(this.queue, msg.task)
    this.changed()
  }

  onStatus(): void {
    void this.card.render()
  }

  private startCapture(): void {
    this.captureId = newCaptureId()
    this.ctx.socket.send({ type: 'capture.start', captureId: this.captureId })
    void this.showScreen('listening')
  }

  private stopCapture(): void {
    if (this.captureId) this.ctx.socket.send({ type: 'capture.stop', captureId: this.captureId })
    this.captureId = null
  }

  onTap(): void {
    if (this.current === 'queue') {
      void this.showScreen('card')
      return
    }
    if (this.current !== 'card') return
    const r = tap(this.queue)
    this.queue = r.queue
    if (r.send) this.ctx.socket.send(r.send)
    this.changed()
  }

  onSwipeUp(): void {
    if (this.current === 'card') void this.showScreen('queue')
    else if (this.current === 'queue') void this.showScreen('card')
  }

  onSwipeDown(): void {
    if (this.current === 'card') this.startCapture()
    else if (this.current === 'listening') {
      this.stopCapture()
      void this.showScreen('card')
    }
  }

  save(): void {
    void saveQueue(this.ctx.bridge, this.queue)
  }

  cleanup(): void {
    this.stopCapture()
    this.save()
  }
}
