import { RebuildPageContainer } from '@evenrealities/even_hub_sdk'
import type { BackendMessage, GlassesJsonMessage, VoiceIntent } from './contract'
import { formatCard, formatQueue } from './card'
import { CaptureScreen } from './capture'
import { RollingBuffer } from './clip'
import { debugFixtures, debugSays, loadFixture } from './debug-pcm'
import { FrameChunker, Mic, toBytes } from './mic'
import type { Hud, HudContext, PageSpec } from './hud'
import { applyBackendTask, markDone, saveDone, type DoneIds } from './reconcile'
import { MAIN_ID, MAIN_NAME, TextSlot, fullTextPage } from './render'
import { saveQueue } from './storage'
import { tap, type Queue } from './tasks'
import { log } from './log'
import { UNDO_MS, voiceAction } from './voice'

type Screen = 'card' | 'queue' | 'draft'

/**
 * The server HUD: one task card, the queue, and the order draft. While the server role is on
 * the glasses the mic runs into a rolling buffer of the last 60 s (memory only); swipe down
 * sends that minute as a clip and opens the draft the backend makes of it.
 */
export class ServerHud implements Hud {
  readonly role = 'server'
  queue: Queue
  private done: DoneIds
  private current: Screen = 'card'
  private readonly card: TextSlot
  private readonly capture: CaptureScreen
  private readonly mic: Mic
  private readonly chunker = new FrameChunker()
  private readonly buffer = new RollingBuffer()
  private readonly fixtures = debugFixtures()
  private nextFixture = 0
  private commandId: string | null = null
  private heard: { text: string; timer: ReturnType<typeof setTimeout>; pending: boolean } | null = null

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
    this.mic = new Mic(ctx.bridge)
    if (this.fixtures.length) log('DEBUG PCM path on:', this.fixtures.join(','))
  }

  /** True while the last minute is being kept (mic on, or a debug fixture loaded). */
  get recording(): boolean {
    return this.mic.isOpen || (this.fixtures.length > 0 && this.buffer.frames > 0)
  }

  get bufferedSeconds(): number {
    return this.buffer.seconds
  }

  /** Mic on into the rolling buffer. In the debug path a fixture stands in for the minute. */
  async startRecording(): Promise<void> {
    if (this.fixtures.length) {
      await this.loadDebugMinute()
      this.openCommandStream()
      void this.playDebugSays()
      return
    }
    const ok = await this.mic.set(true)
    log('rolling buffer', ok ? 'recording (last 60 s, memory only)' : 'mic did not open')
    this.openCommandStream()
    this.ctx.syncPhone()
  }

  /** The live mic also goes to the relay, which only answers "verity <command>". */
  private openCommandStream(): void {
    if (!this.recording || this.commandId || this.ctx.status() !== 'online') return
    this.commandId = `cmd-${Date.now().toString(36)}`
    this.ctx.socket.send({ type: 'capture.start', captureId: this.commandId, mode: 'command' })
  }

  private closeCommandStream(): void {
    if (this.commandId && this.ctx.status() === 'online')
      this.ctx.socket.send({ type: 'capture.stop', captureId: this.commandId })
    this.commandId = null
  }

  /** DEV ONLY: `?say=` fixtures stand in for the server speaking a command. */
  private async playDebugSays(): Promise<void> {
    const silence = Array.from({ length: 15 }, () => new ArrayBuffer(3200))
    for (const name of debugSays()) {
      const frames = await loadFixture(name)
      await new Promise(r => setTimeout(r, 4000))
      for (const f of [...frames, ...silence]) {
        if (this.commandId) this.ctx.socket.sendAudio(f)
        await new Promise(r => setTimeout(r, 100))
      }
    }
  }

  /** Mic off and the minute forgotten (role switch, exit). */
  stopRecording(): void {
    this.closeCommandStream()
    this.clearHeard()
    void this.mic.set(false)
    this.buffer.clear()
    this.chunker.reset()
    this.ctx.syncPhone()
  }

  private async loadDebugMinute(): Promise<void> {
    const name = this.fixtures[this.nextFixture]!
    this.nextFixture = (this.nextFixture + 1) % this.fixtures.length
    const frames = await loadFixture(name)
    this.buffer.clear()
    for (const f of frames.slice(-this.buffer.capacity)) this.buffer.push(f)
    this.ctx.syncPhone()
  }

  screen(): Screen {
    return this.current
  }

  private currentCard() {
    return formatCard(this.queue, { offline: this.ctx.status() !== 'online', banner: this.heard?.text })
  }

  startPage(): PageSpec {
    this.current = 'card'
    const card = this.currentCard()
    this.card.shown(card)
    return { containerTotalNum: 1, textObject: [fullTextPage(card.text, card.brightness)] }
  }

  async enter(): Promise<void> {
    await this.showScreen('card')
    await this.startRecording()
  }

  /** Leaving the role turns the mic off and forgets the minute; the draft is kept. */
  leave(): void {
    this.capture.leave()
    this.stopRecording()
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
    if (msg.type === 'voice.command') return this.onVoiceCommand(msg.intent)
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
    if (this.ctx.status() === 'online') this.openCommandStream()
    else this.commandId = null
    this.capture.setOnline(this.ctx.status() === 'online')
    void this.card.render()
  }

  /** SDK audio event: mic frames go into the rolling buffer, nowhere else. */
  onAudio(pcm: unknown): void {
    if (!this.mic.isOpen || this.fixtures.length) return
    const bytes = toBytes(pcm)
    if (!bytes) return
    for (const frame of this.chunker.push(bytes)) {
      this.buffer.push(frame)
      if (this.commandId) this.ctx.socket.sendAudio(frame)
    }
  }

  /** The accepted ORDER task on top names the table; otherwise the backend or the clip does. */
  private orderTable(): string | undefined {
    const head = this.queue[0]
    return head?.kind === 'ORDER' && head.state === 'accepted' ? head.table : undefined
  }

  /** Swipe down: clip the last minute, send it, show the draft. */
  private async sendClip(): Promise<void> {
    const frames = this.buffer.clip()
    if (this.current !== 'draft') await this.showScreen('draft')
    this.capture.sendClip(frames, this.orderTable())
    if (this.fixtures.length) void this.loadDebugMinute()
  }

  private onDraftGesture(g: 'tap' | 'up' | 'down'): void {
    const then = this.capture.gesture(g)
    if (then === 'back') void this.showScreen('card')
    if (then === 'clip') void this.sendClip()
  }

  /**
   * "verity <command>": the same action as the gesture. Task actions and confirm wait 3 s
   * behind `Heard: <command>`; a tap or "verity back" in that time undoes them.
   */
  onVoiceCommand(intent: VoiceIntent): void {
    log('<- voice.command', intent)
    if (this.heard?.pending && intent === 'back') return this.undoHeard()
    const head = this.queue[0]
    const action = voiceAction(intent, head)
    if (action.kind === 'refuse') return this.showHeard(action.line, null)
    if (intent === 'confirm' && this.current !== 'draft') return this.showHeard('Nothing to confirm', null)
    if (action.kind === 'gesture' && intent !== 'confirm') {
      this.showHeard(`Heard: ${intent}`, null)
      return this.runGesture(action.gesture)
    }
    this.showHeard(`Heard: ${intent}`, () => {
      if (action.kind === 'gesture') this.onDraftGesture('tap')
      else if (this.queue[0]?.id === head?.id) this.sendTask(action.send)
    })
  }

  private runGesture(g: 'tap' | 'up' | 'down' | 'back' | 'clip'): void {
    if (g === 'tap') this.onTap()
    else if (g === 'up') this.onSwipeUp()
    else if (g === 'down') this.onSwipeDown()
    else if (g === 'clip') void this.sendClip()
    else if (this.current !== 'card') void this.showScreen('card')
  }

  private sendTask(send: GlassesJsonMessage): void {
    const head = this.queue[0]
    const viaTap =
      (send.type === 'task.accept' && head?.state === 'assigned') ||
      (send.type === 'task.done' && head?.state === 'accepted')
    if (viaTap) return this.taskTap()
    this.ctx.socket.send(send)
    if (send.type === 'task.done' || send.type === 'task.bounce') {
      const id = send.taskId
      this.queue = this.queue.filter(t => t.id !== id)
      if (send.type === 'task.done') this.done = markDone(this.done, id)
    }
    this.changed()
  }

  private showHeard(text: string, run: (() => void) | null): void {
    this.clearHeard()
    const timer = setTimeout(() => {
      this.heard = null
      run?.()
      this.refreshHeard()
    }, UNDO_MS)
    this.heard = { text, timer, pending: run !== null }
    this.refreshHeard()
  }

  private undoHeard(): void {
    const what = this.heard?.text.replace('Heard: ', '') ?? ''
    this.showHeard(`Undone: ${what}`, null)
  }

  private clearHeard(): void {
    if (this.heard) clearTimeout(this.heard.timer)
    this.heard = null
  }

  private refreshHeard(): void {
    if (this.current === 'draft') this.capture.setHint(this.heard?.text ?? null)
    else void this.card.render()
  }

  onTap(): void {
    if (this.heard?.pending) return this.undoHeard()
    if (this.current === 'draft') return this.onDraftGesture('tap')
    if (this.current === 'queue') {
      void this.showScreen('card')
      return
    }
    this.taskTap()
  }

  private taskTap(): void {
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
    if (this.current === 'card') void this.sendClip()
    else if (this.current === 'draft') this.onDraftGesture('down')
  }

  save(): void {
    void saveQueue(this.ctx.bridge, this.queue)
    void saveDone(this.ctx.bridge, this.done)
  }

  /** Exit: mic off, minute forgotten, state saved. */
  cleanup(): void {
    this.stopRecording()
    this.save()
  }
}
