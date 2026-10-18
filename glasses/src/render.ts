import { TextContainerProperty, TextContainerUpgrade, type EvenAppBridge } from '@evenrealities/even_hub_sdk'
import { CARD_PADDING, DISPLAY_HEIGHT, DISPLAY_WIDTH, TAB_RAIL_WIDTH, type CardView } from './card'
import { TABS, TAB_LABELS, type Tab } from './controls'
import { log } from './log'

export const MAIN_ID = 1
export const MAIN_NAME = 'main'

/** The one full-screen, input-capturing text container both HUDs use for their root screen. */
export function fullTextPage(content: string, brightness = 4): TextContainerProperty {
  return new TextContainerProperty({
    xPosition: 0,
    yPosition: 0,
    width: DISPLAY_WIDTH,
    height: DISPLAY_HEIGHT,
    borderWidth: 0,
    paddingLength: CARD_PADDING,
    containerID: MAIN_ID,
    containerName: MAIN_NAME,
    // An empty string may be rejected by the host; a space renders as blank.
    content: content || ' ',
    textColor: brightness,
    isEventCapture: 1,
  })
}

/** The tab rail's boxes, one per tab, top to bottom like TABS. */
export const TAB_IDS: Record<Tab, number> = { controls: 11, queue: 12, card: 13 }
const TAB_HEIGHT = DISPLAY_HEIGHT / TABS.length

/**
 * A server tab: the rail of stacked tabs on the left (the open one bordered and bright, the
 * others dim) and the content beside it. Only the content captures input and is upgraded in
 * place; the rail only changes when a rebuild switches tabs.
 */
export function tabsPage(active: Tab, view: CardView): { containerTotalNum: number; textObject: TextContainerProperty[] } {
  const rail = TABS.map(
    (tab, i) =>
      new TextContainerProperty({
        xPosition: 0,
        yPosition: i * TAB_HEIGHT,
        width: TAB_RAIL_WIDTH,
        height: TAB_HEIGHT,
        borderWidth: tab === active ? 1 : 0,
        borderColor: 4,
        borderRadius: 6,
        paddingLength: CARD_PADDING,
        containerID: TAB_IDS[tab],
        containerName: `tab-${tab}`,
        content: TAB_LABELS[tab],
        textColor: tab === active ? 4 : 1,
        isEventCapture: 0,
      }),
  )
  const content = new TextContainerProperty({
    xPosition: TAB_RAIL_WIDTH,
    yPosition: 0,
    width: DISPLAY_WIDTH - TAB_RAIL_WIDTH,
    height: DISPLAY_HEIGHT,
    borderWidth: 0,
    paddingLength: CARD_PADDING,
    containerID: MAIN_ID,
    containerName: MAIN_NAME,
    content: view.text || ' ',
    textColor: view.brightness,
    isEventCapture: 1,
  })
  return { containerTotalNum: rail.length + 1, textObject: [...rail, content] }
}

const keyOf = (view: CardView) => JSON.stringify(view)

/**
 * One text container on the glasses, updated in place with `textContainerUpgrade`.
 * Writes are serialized and coalesced so a burst of changes ends on the latest view, and
 * skipped when nothing changed. `current` returns null while the container isn't on screen.
 */
export class TextSlot {
  private shownKey = ''
  private writing = false
  private dirty = false

  constructor(
    private readonly bridge: EvenAppBridge,
    private readonly id: number,
    private readonly name: string,
    private readonly label: string,
    private readonly current: () => CardView | null,
  ) {}

  /** Record what a create or rebuild just drew, so the next render only sends changes. */
  shown(view: CardView): void {
    this.shownKey = keyOf(view)
  }

  async render(): Promise<void> {
    if (!this.current()) return
    if (this.writing) {
      this.dirty = true
      return
    }
    this.writing = true
    try {
      do {
        this.dirty = false
        const view = this.current()
        if (!view) break
        const key = keyOf(view)
        if (key === this.shownKey) continue
        const t0 = performance.now()
        const ok = await this.bridge.textContainerUpgrade(
          new TextContainerUpgrade({
            containerID: this.id,
            containerName: this.name,
            content: view.text || ' ',
            textColor: view.brightness,
          }),
        )
        this.shownKey = key
        log(`${this.label} upgrade`, ok, `${(performance.now() - t0).toFixed(1)} ms`, JSON.stringify(view.text))
      } while (this.dirty)
    } finally {
      this.writing = false
    }
  }
}
