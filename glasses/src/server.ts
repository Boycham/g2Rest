import { RebuildPageContainer } from '@evenrealities/even_hub_sdk'
import type { BackendMessage, GlassesJsonMessage, VoiceCommand } from './contract'
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
import { CONTROLS, CONTROLS_HINT, MAIN_GESTURES, formatControls, moveSelection, type ControlAction } from './controls'
import { handoffFrame, handoffPrompt } from './handoff'
import { didntGet, voiceAction, type VoiceGesture } from './voice'

/** How long `Heard: <command>` and refusal lines stay on the card. */
const FLASH_MS = 3000

type Screen = 'card' | 'queue' | 'draft' | 'controls'

/**
 * The server HUD: one task card, the queue, and the order draft. While the server role is on
 * the glasses the mic runs into a rolling buffer of the last 60 s (memory only); swipe back
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
  private heard: { text: string; timer: ReturnType<typeof setTimeout> } | null = null
  private popup: { taskId: string; name?: string } | null = null
  private selected = 0
  /** task.revert is in flight: the next task update is its answer. */
  private revertSent = false

  constructor(
    private readonly ctx: HudContext,
    restored: Queue,
    restoredDone: DoneIds,
  ) {
    this.queue = restored
    this.done = restoredDone
    this.card = new TextSlot(ctx.bridge, MAIN_ID, MAIN_NAME, 'card', () =>
      ctx.active() ? this.slotView() : null,
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
      for (const [i, f] of [...frames, ...silence].entries()) {
        if (i === frames.length) log('debug say spoken', name)
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

  private banner(): string | undefined {
    if (this.popup && this.queue[0]?.id === this.popup.taskId) return handoffPrompt(this.popup.name)
    return this.heard?.text
  }

  private currentCard() {
    const offline = this.ctx.status() !== 'online'
    return formatCard(this.queue, { offline, banner: this.banner(), hint: CONTROLS_HINT })
  }

  /** What the main text container shows on the card, Controls and queue screens (null on the draft). */
  private slotView() {
    if (this.current === 'card') return this.currentCard()
    if (this.current === 'controls') return { text: formatControls(this.selected), brightness: 4 }
    if (this.current === 'queue') return { text: formatQueue(this.queue), brightness: 4 }
    return null
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
    const view = this.slotView() ?? { text: '', brightness: 4 }
    const page = new RebuildPageContainer({ containerTotalNum: 1, textObject: [fullTextPage(view.text, view.brightness)] })
    this.card.shown(view)
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
    if (msg.type === 'voice.command') return this.onVoiceCommand(msg)
    if (msg.type === 'voice.unknown') {
      log('<- voice.unknown', msg.reason ?? '')
      return this.flash(didntGet(msg.words, msg.reason))
    }
    if (msg.type === 'task.rejected') {
      if (msg.action === 'revert') this.revertSent = false
      log('<- task.rejected', msg.action, msg.taskId ?? '', msg.reason)
      return this.flash(msg.reason)
    }
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
    const reverted = this.revertSent
    this.revertSent = false
    const r = applyBackendTask(this.queue, this.done, msg.task, reverted)
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

  /** Swipe back: clip the last minute, send it, show the draft. */
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

  /** "verity <command>": the same action as the gesture; task frames go out at once. */
  onVoiceCommand(cmd: VoiceCommand): void {
    log('<- voice.command', cmd.intent, cmd.name ?? '')
    const action = voiceAction(cmd.intent, this.queue[0], cmd.name)
    switch (action.kind) {
      case 'refuse':
        return this.flash(action.line)
      case 'confirm':
        this.flash('Heard: confirm')
        return this.onTap()
      case 'nevermind':
        if (!this.popup) return this.flash('Nothing to cancel')
        this.popup = null
        return this.flash('Cancelled')
      case 'handoff':
        this.flash(`Heard: handoff${action.name ? ` ${action.name}` : ''}`)
        return this.openHandoff(action.name)
      case 'task':
        this.flash(`Heard: ${cmd.intent}`)
        return this.sendTask(action.send)
      case 'gesture':
        this.flash(`Heard: ${cmd.intent}`)
        return this.voiceGesture(action.gesture)
    }
  }

  private voiceGesture(g: VoiceGesture): void {
    if (g === 'up') return this.onSwipeUp()
    if (g === 'down') return this.onSwipeDown()
    if (g === 'clip') return void this.sendClip()
    if (g === 'menu') return void this.openControls()
    if (g === 'queue') return void this.showScreen('queue')
    if (this.popup) {
      this.popup = null
      return this.refreshHeard()
    }
    if (this.current !== 'card') void this.showScreen('card')
  }

  /** Task frames from voice or the menu; the backend answers task.updated or task.rejected. */
  private sendTask(send: GlassesJsonMessage): void {
    const head = this.queue[0]
    const viaTap =
      (send.type === 'task.accept' && head?.state === 'assigned' && head.id === send.taskId) ||
      (send.type === 'task.done' && head?.state === 'accepted' && head.id === send.taskId)
    if (viaTap) return this.taskTap()
    if (send.type === 'task.revert') this.revertSent = true
    this.ctx.socket.send(send)
  }

  /** Long hold or "verity handoff [name]": a Confirm popup on the card first. */
  private openHandoff(name?: string): void {
    const head = this.queue[0]
    if (!head) return this.flash('No task to hand off')
    if (this.current !== 'card') void this.showScreen('card')
    this.popup = name ? { taskId: head.id, name } : { taskId: head.id }
    this.refreshHeard()
  }

  private confirmHandoff(): void {
    const popup = this.popup
    this.popup = null
    if (!popup) return
    log('-> task.handoff', popup.taskId, popup.name ?? '(router picks)')
    this.ctx.socket.send(handoffFrame(popup.taskId, popup.name))
    this.flash(popup.name ? `Handing off to ${popup.name}` : 'Handing off')
  }

  private async openControls(): Promise<void> {
    this.selected = 0
    await this.showScreen('controls')
  }

  /** A tap (or "verity confirm") on the selected Controls row. */
  private pick(action: ControlAction): void {
    log('controls pick', action)
    if (action === 'queue') return void this.showScreen('queue')
    if (action === 'clip') return void this.sendClip()
    if (action === 'exit') return void this.ctx.bridge.shutDownPageContainer(1)
    void this.showScreen('card')
    if (action === 'task') this.taskTap()
    else if (action === 'handoff') this.openHandoff()
    else if (action === 'decline' && this.queue[0]) this.sendTask({ type: 'task.bounce', taskId: this.queue[0].id })
    else if (action === 'revert') this.sendTask({ type: 'task.revert' })
    else if (action === 'controls') void this.openControls()
  }

  /** What a gesture does on the main card (MAIN_GESTURES in controls.ts). */
  private mainAction(action: 'task' | 'controls' | 'queue' | 'clip' | 'handoff'): void {
    if (action === 'task') return this.taskTap()
    if (action === 'controls') return void this.openControls()
    if (action === 'queue') return void this.showScreen('queue')
    if (action === 'clip') return void this.sendClip()
    this.openHandoff()
  }

  private flash(text: string): void {
    this.clearHeard()
    const timer = setTimeout(() => {
      this.heard = null
      this.refreshHeard()
    }, FLASH_MS)
    this.heard = { text, timer }
    this.refreshHeard()
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
    if (this.popup) return this.confirmHandoff()
    if (this.current === 'draft') return this.onDraftGesture('tap')
    if (this.current === 'controls') return this.pick(CONTROLS[this.selected].action)
    if (this.current === 'queue') return void this.showScreen('card')
    this.mainAction(MAIN_GESTURES.tap)
  }

  private taskTap(): void {
    const r = tap(this.queue)
    this.queue = r.queue
    if (r.send) this.ctx.socket.send(r.send)
    if (r.send?.type === 'task.done') this.done = markDone(this.done, r.send.taskId)
    this.changed()
  }

  onSwipeUp(): void {
    if (this.current === 'draft') return this.onDraftGesture('up')
    if (this.current === 'controls') return this.move('up')
    if (this.current === 'queue') return void this.showScreen('card')
    this.mainAction(MAIN_GESTURES.up)
  }

  onSwipeDown(): void {
    if (this.current === 'draft') return this.onDraftGesture('down')
    if (this.current === 'controls') return this.move('down')
    if (this.current === 'queue') return void this.showScreen('card')
    this.mainAction(MAIN_GESTURES.down)
  }

  /** Long hold (LONG_PRESS_EVENT): handoff on the card; in Controls it goes back, like Close. */
  onLongPress(): void {
    if (this.current === 'controls') return void this.showScreen('card')
    if (this.current === 'card') this.mainAction(MAIN_GESTURES.hold)
  }

  private move(dir: 'up' | 'down'): void {
    this.selected = moveSelection(this.selected, dir)
    void this.card.render()
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
