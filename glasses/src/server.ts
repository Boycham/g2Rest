import { RebuildPageContainer } from '@evenrealities/even_hub_sdk'
import type { BackendMessage } from './contract'
import { formatCard, formatQueue } from './card'
import { CaptureScreen } from './capture'
import type { Hud, HudContext, PageSpec } from './hud'
import { applyBackendTask, markDone, saveDone, type DoneIds } from './reconcile'
import { MAIN_ID, MAIN_NAME, TextSlot, fullTextPage } from './render'
import { saveQueue } from './storage'
import { tap, type Queue } from './tasks'
import { log } from './log'

type Screen = 'card' | 'queue' | 'draft'

/** The server HUD: one task card, the queue, and the voice capture / draft screen. */
export class ServerHud implements Hud {
  readonly role = 'server'
  queue: Queue
  private done: DoneIds
  private current: Screen = 'card'
  private readonly card: TextSlot
  private readonly capture: CaptureScreen

  constructor(
    private readonly ctx: HudContext,
    restored: Queue,
    restoredDone: DoneIds,
  ) {
    this.queue = restored
    this.done = restoredDone
    this.card = new TextSlot(ctx.bridge, MAIN_ID, MAIN_NAME, 'card', () =>
      ctx.active() && this.current === 'card' ? this.currentCard() : null,
    )
    this.capture = new CaptureScreen(ctx.bridge, ctx.socket, () => ctx.syncPhone())
  }

  get capturing(): boolean {
    return this.capture.capturing
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

  /** Leaving the role always turns the mic off; the draft is kept. */
  leave(): void {
    this.capture.leave()
    this.current = 'card'
  }

  private async showScreen(next: Screen): Promise<void> {
    if (this.current === 'draft' && next !== 'draft') this.capture.leave()
    this.current = next
    if (next === 'draft') {
      await this.capture.enter()
      this.ctx.syncPhone()
      return
    }
    const card = this.currentCard()
    const text = next === 'queue' ? formatQueue(this.queue) : card.text
    const brightness = next === 'card' ? card.brightness : 4
    const page = new RebuildPageContainer({ containerTotalNum: 1, textObject: [fullTextPage(text, brightness)] })
    if (next === 'card') this.card.shown(card)
    const t0 = performance.now()
    const ok = await this.ctx.bridge.rebuildPageContainer(page)
    log('rebuild', next, ok, `${(performance.now() - t0).toFixed(1)} ms`)
    this.ctx.syncPhone()
  }

  private changed(): void {
    this.save()
    void this.card.render()
    this.ctx.syncPhone()
  }

  onMessage(msg: BackendMessage): void {
    if (msg.type === 'order.draft') {
      log('<-', msg.type, msg.orderId, msg.voice ?? '', `${msg.lines.length} lines`, `${msg.pending?.length ?? 0} pending`)
      this.capture.onDraft(msg)
      return
    }
    if (msg.type === 'order.closed') {
      log('<-', msg.type, msg.orderId, msg.status)
      if (this.capture.onClosed(msg) && this.current === 'draft') void this.showScreen('card')
      return
    }
    if (msg.type !== 'task.assigned' && msg.type !== 'task.updated') return
    log('<-', msg.type, msg.task.id, msg.task.state)
    const r = applyBackendTask(this.queue, this.done, msg.task)
    this.queue = r.queue
    this.done = r.done
    for (const m of r.resend) this.ctx.socket.send(m)
    if (r.resend.length) log('re-sent after replay', r.resend.map(m => m.type).join(' '))
    this.changed()
  }

  onStatus(): void {
    this.capture.setOnline(this.ctx.status() === 'online')
    void this.card.render()
  }

  /** SDK audio event; CaptureScreen forwards it only while capturing from the mic. */
  onAudio(pcm: unknown): void {
    this.capture.onAudio(pcm)
  }

  private async startCapture(): Promise<void> {
    await this.showScreen('draft')
    this.capture.start()
  }

  private onDraftGesture(g: 'tap' | 'up' | 'down'): void {
    if (this.capture.gesture(g) === 'back') void this.showScreen('card')
  }

  onTap(): void {
    if (this.current === 'draft') return this.onDraftGesture('tap')
    if (this.current === 'queue') {
      void this.showScreen('card')
      return
    }
    const r = tap(this.queue)
    this.queue = r.queue
    if (r.send) this.ctx.socket.send(r.send)
    if (r.send?.type === 'task.done') this.done = markDone(this.done, r.send.taskId)
    this.changed()
  }

  onSwipeUp(): void {
    if (this.current === 'draft') this.onDraftGesture('up')
    else if (this.current === 'card') void this.showScreen('queue')
    else void this.showScreen('card')
  }

  onSwipeDown(): void {
    if (this.current === 'card') void this.startCapture()
    else if (this.current === 'draft') this.onDraftGesture('down')
  }

  save(): void {
    void saveQueue(this.ctx.bridge, this.queue)
    void saveDone(this.ctx.bridge, this.done)
  }

  /** Background or exit: mic off, state saved. */
  cleanup(): void {
    this.capture.stop()
    this.save()
  }
}
