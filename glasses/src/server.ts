import { RebuildPageContainer } from '@evenrealities/even_hub_sdk'
import type { BackendMessage, GlassesJsonMessage, VoiceCommand, VoiceRequest } from './contract'
import { TAB_TEXT_WIDTH, formatCard, formatQueue } from './card'
import { EightySix } from './eightysix'
import { CaptureScreen } from './capture'
import { RollingBuffer } from './clip'
import { debugFixtures, debugSays, loadFixture } from './debug-pcm'
import { FrameChunker, Mic, toBytes } from './mic'
import type { Hud, HudContext, PageSpec } from './hud'
import { applyBackendTask, markDone, saveDone, type DoneIds } from './reconcile'
import { MAIN_ID, MAIN_NAME, TextSlot, blankPage, fullTextPage, tabsPage } from './render'
import { saveQueue, saveRamp } from './storage'
import { formatRamp, rampHint, rampOn, rampPages, withRamp, type RampPrefs } from './ramp'
import { tap, type Queue } from './tasks'
import { DONE_BEAT_MS, IdleBlank } from './idle'
import { log } from './log'
import { CARD_GESTURES, CARD_HINT, formatControls, nextControlsPage, tabAfter, type CardAction, type Tab } from './controls'
import { handoffFrame, handoffPrompt } from './handoff'
import { PROCESSING, Ticker, dots } from './busy'
import { didntGet, rejectionLine, tableLine, voiceAction, type VoiceGesture } from './voice'
import { refusedLine, requestFrame, requestLine, sentLine } from './request'

/** How long `Heard: <command>` and refusal lines stay on the card. */
const FLASH_MS = 3000
/** Gemini's own timeout is 2 s; past this the relay is gone and the words show as not got. */
const MAPPING_TIMEOUT_MS = 5000
/** The Task tab's top line on a tap wake with nothing to do. */
const NO_TASKS = 'No tasks'

type Screen = Tab | 'draft' | 'ramp'

/** Who wears the glasses (for their ramp-hint setting) and the saved settings. */
export interface RampSettings {
  staff: string
  prefs: RampPrefs
}

/**
 * The server HUD: three stacked tabs (Controls, Queue, Task; it starts on the Task tab) and the
 * order draft. While the server role is on
 * the glasses the mic runs into a rolling buffer of the last 120 s (memory only); swipe back
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
  private mapping: { words: string; timer: ReturnType<typeof setTimeout> } | null = null
  private readonly mappingTicker = new Ticker(() => {
    if (this.current !== 'draft') void this.card.render()
  })
  private popup: { taskId: string; name?: string } | null = null
  /** A spoken floor request or table status waiting for its confirm tap. */
  private request: VoiceRequest | null = null
  private controlsPage = 0
  /** task.revert is in flight: the next task update is its answer. */
  private revertSent = false
  private readonly out86 = new EightySix()
  private rampPage = 0
  private readonly idle = new IdleBlank(awake => this.onIdle(awake))
  /** The blank page is on the glasses (idle.ts): nothing renders until a wake rebuilds. */
  private blankShown = false

  constructor(
    private readonly ctx: HudContext,
    restored: Queue,
    restoredDone: DoneIds,
    private ramp: RampSettings = { staff: '', prefs: {} },
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

  /** True while the last 2 minutes are being kept (mic on, or a debug fixture loaded). */
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
    log('rolling buffer', ok ? 'recording (last 120 s, memory only)' : 'mic did not open')
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

  screen(): Screen | 'blank' {
    return this.blankShown ? 'blank' : this.current
  }

  /** Something on the glasses needs the screen, so it must not blank. */
  private held(): boolean {
    return (
      this.queue.length > 0 ||
      this.current === 'draft' ||
      this.current === 'ramp' ||
      this.popup !== null ||
      this.request !== null ||
      this.mapping !== null ||
      this.capture.processing
    )
  }

  private syncIdle(): void {
    if (this.ctx.active()) this.idle.update(this.held())
  }

  /** Idle timer: blank the glasses, or bring the Task tab back from blank. */
  private onIdle(awake: boolean): void {
    if (!this.ctx.active()) return
    if (awake) {
      if (this.blankShown) void this.showScreen(this.current)
      return
    }
    void this.showBlank()
  }

  private async showBlank(): Promise<void> {
    if (this.current === 'draft') this.capture.leave()
    this.current = 'card'
    this.popup = null
    this.blankShown = true
    const t0 = performance.now()
    const ok = await this.ctx.bridge.rebuildPageContainer(new RebuildPageContainer(blankPage()))
    log('rebuild blank (idle)', ok, `${(performance.now() - t0).toFixed(1)} ms`)
    this.ctx.syncPhone()
  }

  /** While blank, a tap (or swipe fwd, long press) only brings the Task tab back. */
  private wokeByGesture(): boolean {
    this.idle.touch()
    if (!this.blankShown) return false
    log('wake: gesture')
    this.idle.wake()
    return true
  }

  private banner(): string | undefined {
    if (this.request) return requestLine(this.request)
    if (this.popup && this.queue[0]?.id === this.popup.taskId) return handoffPrompt(this.popup.name)
    if (this.mapping) return dots(PROCESSING, this.mappingTicker.tick)
    return this.heard?.text
  }

  private currentCard() {
    const offline = this.ctx.status() !== 'online'
    return formatCard(this.queue, {
      offline,
      banner: this.banner(),
      eightySix: this.out86.line(),
      hint: CARD_HINT,
      empty: NO_TASKS,
      width: TAB_TEXT_WIDTH,
      detail: rampOn(this.ramp.prefs, this.ramp.staff) ? rampHint(this.queue[0], TAB_TEXT_WIDTH) : undefined,
    })
  }

  /** What the tab content shows (null on the draft). */
  private slotView() {
    if (this.blankShown) return null
    if (this.current === 'card') return this.currentCard()
    if (this.current === 'controls') return { text: formatControls(this.controlsPage), brightness: 4 }
    if (this.current === 'queue') return { text: formatQueue(this.queue), brightness: 4 }
    if (this.current === 'ramp' && this.queue[0]) return formatRamp(this.queue[0], this.rampPage)
    return null
  }

  startPage(): PageSpec {
    this.current = 'card'
    this.blankShown = false
    const card = this.currentCard()
    this.card.shown(card)
    // Starts awake (the wearer sees the app is up), then blanks after IDLE_MS if idle.
    if (this.ctx.active()) this.syncIdle()
    return tabsPage('card', card)
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
    this.idle.reset()
    this.blankShown = false
  }

  private async showScreen(next: Screen): Promise<void> {
    if (this.current === 'draft' && next !== 'draft') this.capture.leave()
    if (next !== 'card') this.popup = null
    this.current = next
    this.blankShown = false
    if (this.ctx.active()) {
      if (this.held()) this.idle.update(true)
      else this.idle.wake()
    }
    if (next === 'draft') {
      await this.capture.enter()
      this.ctx.syncPhone()
      return
    }
    const view = this.slotView() ?? { text: '', brightness: 4 }
    // The ramp view is full width, without the tab rail: it is the card's detail, not a tab.
    const spec = next === 'ramp' ? { containerTotalNum: 1, textObject: [fullTextPage(view.text, view.brightness)] } : tabsPage(next, view)
    const page = new RebuildPageContainer(spec)
    this.card.shown(view)
    const t0 = performance.now()
    const ok = await this.ctx.bridge.rebuildPageContainer(page)
    log('rebuild', next, ok, `${(performance.now() - t0).toFixed(1)} ms`)
    this.ctx.syncPhone()
  }

  private changed(): void {
    this.save()
    // The head task left or names no dishes any more: the ramp view has nothing to show.
    if (this.current === 'ramp' && !rampPages(this.queue[0]).length) void this.showScreen('card')
    else {
      this.syncIdle()
      void this.card.render()
    }
    this.ctx.syncPhone()
  }

  onMessage(msg: BackendMessage): void {
    if (msg.type === 'voice.mapping') return this.setMapping(msg.words)
    if (msg.type === 'voice.command' || msg.type === 'voice.unknown') this.setMapping(null)
    if (msg.type === 'voice.command') return this.onVoiceCommand(msg)
    if (msg.type === 'voice.request') return this.onRequest(msg)
    if (msg.type === 'alert') {
      if (!this.out86.apply(msg)) return
      if (this.ctx.active()) this.idle.wake()
      void this.card.render()
      return
    }
    if (msg.type === 'voice.unknown') {
      log('<- voice.unknown', msg.reason ?? '')
      if (this.ctx.active()) this.idle.wake()
      return this.flash(didntGet(msg.words, msg.reason))
    }
    if (msg.type === 'task.rejected') {
      if (msg.action === 'revert') this.revertSent = false
      log('<- task.rejected', msg.action, msg.taskId ?? '', msg.reason)
      return this.flash(rejectionLine(msg, this.queue.find(t => t.id === msg.taskId)))
    }
    if (msg.type === 'order.draft') {
      log('<-', msg.type, msg.orderId, msg.voice ?? '', `${msg.lines.length} lines`, `${msg.pending?.length ?? 0} pending`)
      this.capture.onDraft(msg)
      // A clip result while blank (the wearer had left the draft): bring the draft back.
      if (this.blankShown && this.ctx.active()) void this.showScreen('draft')
      else this.syncIdle()
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

  /** Swipe back: clip the last 2 minutes, send it, show the draft. */
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
    log('<- voice.command', cmd.intent, cmd.name ?? cmd.table ?? '', cmd.reason ?? '')
    this.idle.touch()
    // "verity ramp" needs a screen even to say `No dishes to ramp`: wake first (menu and queue wake by opening their tab).
    if (cmd.intent === 'ramp' && this.blankShown && this.ctx.active()) this.idle.wake()
    if (cmd.intent === 'table') return this.flash(tableLine(cmd))
    const action = voiceAction(cmd.intent, this.queue[0], cmd.name, cmd.toggle)
    switch (action.kind) {
      case 'ramp':
        if (action.toggle) return this.setRampHints(action.toggle === 'on')
        this.flash('Heard: ramp')
        return void this.openRamp()
      case 'refuse':
        return this.flash(action.line)
      case 'confirm':
        this.flash('Heard: confirm')
        return this.onTap()
      case 'nevermind':
        if (this.request) {
          this.request = null
          this.syncIdle()
          return this.flash('Request dropped')
        }
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

  /** "verity ramp": the head task's dishes, one per page. */
  private async openRamp(): Promise<void> {
    if (!rampPages(this.queue[0]).length) return this.flash('No dishes to ramp')
    this.rampPage = 0
    await this.showScreen('ramp')
  }

  /** "verity ramp on/off" for the wearer only, kept in SDK storage across reloads. */
  private setRampHints(on: boolean): void {
    this.ramp = { ...this.ramp, prefs: withRamp(this.ramp.prefs, this.ramp.staff, on) }
    log('ramp hints', this.ramp.staff, on ? 'on' : 'off')
    void saveRamp(this.ctx.bridge, this.ramp.prefs)
    this.flash(`Ramp hints ${on ? 'on' : 'off'}`)
  }

  private async openControls(): Promise<void> {
    this.controlsPage = 0
    await this.showScreen('controls')
  }

  /** A swipe on a tab: one tab up or down; null past the ends. */
  private switchTab(dir: 'up' | 'down'): void {
    if (this.current === 'draft') return
    if (this.current === 'ramp') return void this.showScreen('card')
    const next = tabAfter(this.current, dir)
    if (next === 'controls') return void this.openControls()
    if (next) void this.showScreen(next)
  }

  /** What a gesture does on the Task tab (CARD_GESTURES in controls.ts). */
  private cardAction(action: CardAction): void {
    if (action === 'task') return this.taskTap()
    if (action === 'queue') return this.switchTab('up')
    if (action === 'clip') return void this.sendClip()
    this.openHandoff()
  }

  /** `Verity: processing...` in the banner (card) or the bar (draft) while Gemini maps `words`. */
  private setMapping(words: string | null): void {
    if (this.mapping) clearTimeout(this.mapping.timer)
    this.mapping = null
    if (words !== null) {
      log('<- voice.mapping')
      const timer = setTimeout(() => {
        this.setMapping(null)
        this.flash(didntGet(words, 'timeout'))
      }, MAPPING_TIMEOUT_MS)
      this.mapping = { words, timer }
    }
    this.syncIdle()
    this.mappingTicker.set(this.mapping !== null)
    this.capture.setMapping(this.mapping !== null)
    if (this.current !== 'draft') void this.card.render()
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

  private onRequest(r: VoiceRequest): void {
    log('<- voice.request', r.source, r.kind ?? '', r.status ?? '', r.table, r.reason ?? '')
    if (r.reason) return this.flash(refusedLine(r))
    this.request = r
    this.syncIdle()
    this.refreshHeard()
  }

  /** The confirm tap: the backend creates the task or sets the status (and its task). */
  private confirmRequest(r: VoiceRequest): void {
    this.request = null
    this.syncIdle()
    const frame = requestFrame(r)
    if (!frame) return
    log('->', frame.type, frame.table)
    this.ctx.socket.send(frame)
    this.flash(sentLine(r))
  }

  private refreshHeard(): void {
    const line = this.request ? requestLine(this.request) : this.heard?.text
    if (this.current === 'draft') this.capture.setHint(line ?? null)
    else void this.card.render()
  }

  onTap(): void {
    if (this.wokeByGesture()) return
    if (this.request) return this.confirmRequest(this.request)
    if (this.popup) return this.confirmHandoff()
    if (this.current === 'draft') return this.onDraftGesture('tap')
    if (this.current === 'controls') return this.flipControls()
    if (this.current === 'ramp') return this.flipRamp()
    if (this.current === 'queue') return void this.showScreen('card')
    this.cardAction(CARD_GESTURES.tap)
  }

  private taskTap(): void {
    const r = tap(this.queue)
    this.queue = r.queue
    if (r.send) this.ctx.socket.send(r.send)
    if (r.send?.type === 'task.done') this.done = markDone(this.done, r.send.taskId)
    this.changed()
    // The last task done: a short beat on `Done`, then blank.
    if (r.send?.type === 'task.done' && !this.held() && this.ctx.active()) {
      this.flash('Done')
      this.idle.wake(DONE_BEAT_MS)
    }
  }

  onSwipeUp(): void {
    if (this.wokeByGesture()) return
    if (this.current === 'draft') return this.onDraftGesture('up')
    if (this.current === 'card') return this.cardAction(CARD_GESTURES.up)
    this.switchTab('up')
  }

  /** Swipe back while blank still clips (the draft and its processing indicator come up). */
  onSwipeDown(): void {
    this.idle.touch()
    if (this.current === 'draft') return this.onDraftGesture('down')
    if (this.current === 'card') return this.cardAction(CARD_GESTURES.down)
    this.switchTab('down')
  }

  /** Long hold (LONG_PRESS_EVENT): handoff on the Task tab; on Queue, Controls or the ramp view back to the Task tab. */
  onLongPress(): void {
    if (this.wokeByGesture()) return
    if (this.current === 'card') return this.cardAction(CARD_GESTURES.hold)
    if (this.current !== 'draft') void this.showScreen('card')
  }

  /** A tap on the ramp view shows the next dish, wrapping around. */
  private flipRamp(): void {
    this.rampPage = (this.rampPage + 1) % Math.max(1, rampPages(this.queue[0]).length)
    log('ramp page', this.rampPage + 1)
    void this.card.render()
  }

  /** A tap on Controls (or "verity confirm") shows its next page. */
  private flipControls(): void {
    this.controlsPage = nextControlsPage(this.controlsPage)
    log('controls page', this.controlsPage + 1)
    void this.card.render()
  }

  save(): void {
    void saveQueue(this.ctx.bridge, this.queue)
    void saveDone(this.ctx.bridge, this.done)
  }

  /** Exit: mic off, minute forgotten, state saved. */
  cleanup(): void {
    this.stopRecording()
    this.idle.reset()
    this.save()
  }
}
