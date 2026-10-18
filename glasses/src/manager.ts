import { RebuildPageContainer, TextContainerProperty } from '@evenrealities/even_hub_sdk'
import type { BackendMessage } from './contract'
import { applyAlert, dismissTop, formatExceptions, type Exceptions } from './exceptions'
import type { Hud, HudContext, PageSpec } from './hud'
import { BOX_BORDER, BOX_PADDING, MAX_TABLES, applyFloor, layoutKey, minimapView, type BoxView, type FloorTable } from './minimap'
import { MAIN_ID, MAIN_NAME, TextSlot, fullTextPage } from './render'
import { saveManager, type ManagerCache } from './storage'
import { log } from './log'

type Screen = 'exceptions' | 'minimap'

/** Timers on the glasses tick this often; slots only send when the text changes. */
const TICK_MS = 1000
const NO_FLOOR_TEXT = 'No floor data yet'
/** Fixed border level; borders can't be upgraded in place, so urgency rides on text brightness. */
const BOX_BORDER_COLOR = 2

const boxName = (i: number) => `tbl-${i + 1}`

function boxContainer(view: BoxView, i: number): TextContainerProperty {
  return new TextContainerProperty({
    xPosition: view.x,
    yPosition: view.y,
    width: view.w,
    height: view.h,
    borderWidth: BOX_BORDER,
    borderColor: BOX_BORDER_COLOR,
    paddingLength: BOX_PADDING,
    containerID: i + 1,
    containerName: boxName(i),
    content: view.text || ' ',
    textColor: view.brightness,
    // Only one container per page captures input; the first box takes it.
    isEventCapture: i === 0 ? 1 : 0,
  })
}

/** The manager HUD: exceptions by default, swipe back for the floor minimap. */
export class ManagerHud implements Hud {
  readonly role = 'manager'
  exceptions: Exceptions
  tables: FloorTable[]
  private current: Screen = 'exceptions'
  /** Layout drawn by the last minimap rebuild; a different layout needs a rebuild. */
  private shownLayout: string | null = null
  private readonly main: TextSlot
  private readonly boxes: TextSlot[]

  constructor(
    private readonly ctx: HudContext,
    restored: ManagerCache,
  ) {
    this.exceptions = restored.exceptions
    this.tables = restored.tables
    this.main = new TextSlot(ctx.bridge, MAIN_ID, MAIN_NAME, 'exceptions', () =>
      ctx.active() && this.current === 'exceptions' ? this.exceptionsView() : null,
    )
    this.boxes = Array.from(
      { length: MAX_TABLES },
      (_, i) =>
        new TextSlot(ctx.bridge, i + 1, boxName(i), `box ${i + 1}`, () => {
          if (!ctx.active() || this.current !== 'minimap') return null
          const views = this.boxViews()
          return layoutKey(views) === this.shownLayout ? (views[i] ?? null) : null
        }),
    )
    setInterval(() => this.render(), TICK_MS)
  }

  screen(): Screen {
    return this.current
  }

  private exceptionsView() {
    return formatExceptions(this.exceptions, Date.now(), { offline: this.ctx.status() !== 'online' })
  }

  private boxViews(): BoxView[] {
    return minimapView(this.tables, Date.now())
  }

  private exceptionsPage(): PageSpec {
    const view = this.exceptionsView()
    this.main.shown(view)
    return { containerTotalNum: 1, textObject: [fullTextPage(view.text, view.brightness)] }
  }

  private minimapPage(): PageSpec {
    const views = this.boxViews()
    this.shownLayout = layoutKey(views)
    if (!views.length) return { containerTotalNum: 1, textObject: [fullTextPage(NO_FLOOR_TEXT, 2)] }
    views.forEach((v, i) => this.boxes[i]!.shown(v))
    return { containerTotalNum: views.length, textObject: views.map(boxContainer) }
  }

  startPage(): PageSpec {
    this.current = 'exceptions'
    return this.exceptionsPage()
  }

  enter(): Promise<void> {
    return this.showScreen('exceptions')
  }

  leave(): void {
    this.current = 'exceptions'
  }

  private async showScreen(next: Screen): Promise<void> {
    this.current = next
    const spec = next === 'minimap' ? this.minimapPage() : this.exceptionsPage()
    const t0 = performance.now()
    const ok = await this.ctx.bridge.rebuildPageContainer(new RebuildPageContainer(spec))
    log('rebuild', next, spec.containerTotalNum, ok, `${(performance.now() - t0).toFixed(1)} ms`)
    this.ctx.syncPhone()
  }

  private render(): void {
    if (!this.ctx.active()) return
    if (this.current === 'exceptions') {
      void this.main.render()
      return
    }
    if (layoutKey(this.boxViews()) !== this.shownLayout) {
      void this.showScreen('minimap')
      return
    }
    for (const slot of this.boxes) void slot.render()
  }

  private changed(): void {
    this.save()
    this.render()
    this.ctx.syncPhone()
  }

  onMessage(msg: BackendMessage): void {
    if (msg.type === 'alert') {
      log('<- alert', msg.id, msg.level, msg.cleared ? 'cleared' : JSON.stringify(msg.text))
      this.exceptions = applyAlert(this.exceptions, msg, Date.now())
      this.changed()
    } else if (msg.type === 'floor.state') {
      this.tables = applyFloor(msg, Date.now())
      log('<- floor.state', msg.tables.map(t => `${t.table}:${t.status}/${t.urgency}`).join(' '))
      if (msg.tables.length > MAX_TABLES) log('floor has', msg.tables.length, 'tables; minimap shows', MAX_TABLES)
      this.changed()
    }
  }

  onStatus(): void {
    this.render()
  }

  onTap(): void {
    if (this.current === 'minimap') {
      void this.showScreen('exceptions')
      return
    }
    const r = dismissTop(this.exceptions, Date.now())
    if (!r.dismissed) return
    // No ack message in the contract yet (alert.ack is proposed), so this is local only.
    log('dismissed locally', r.dismissed.id)
    this.exceptions = r.state
    this.changed()
  }

  onSwipeUp(): void {
    if (this.current === 'minimap') void this.showScreen('exceptions')
  }

  onSwipeDown(): void {
    if (this.current === 'exceptions') void this.showScreen('minimap')
  }

  onLongPress(): void {}

  save(): void {
    void saveManager(this.ctx.bridge, { exceptions: this.exceptions, tables: this.tables })
  }

  cleanup(): void {
    this.save()
  }
}
