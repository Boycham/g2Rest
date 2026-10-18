import { CARD_MAX_LINES, TAB_TEXT_WIDTH, spread } from './card'

// The gesture map in one place. The server HUD is a vertical stack of three tabs, top to bottom
// TABS; swipe fwd (SDK `up`) goes one tab up and swipe back (SDK `down`) one tab down. The Card is
// the bottom tab, so its swipe back is free for clip: CARD_GESTURES says what each gesture does there.
// On the G2 touchpad SDK `up` is a swipe fwd (toward the eyes) and `down` a swipe back (toward the
// ear). Double tap is always exit (Even Hub review rule) and lives in main.ts.

export const TABS = ['controls', 'queue', 'card'] as const
export type Tab = (typeof TABS)[number]

export const TAB_LABELS: Record<Tab, string> = { controls: 'Controls', queue: 'Queue', card: 'Card' }

/** The tab a swipe moves to; null past the ends (swipe back on the Card is clip instead). */
export function tabAfter(tab: Tab, dir: 'up' | 'down'): Tab | null {
  const i = TABS.indexOf(tab) + (dir === 'up' ? -1 : 1)
  return TABS[i] ?? null
}

export type CardAction = 'task' | 'queue' | 'clip' | 'handoff'

export const CARD_GESTURES: Record<'tap' | 'up' | 'down' | 'hold', CardAction> = {
  tap: 'task',
  up: 'queue',
  down: 'clip',
  hold: 'handoff',
}

/** The Card's corner hint (bottom right): the Queue tab is above it. */
export const CARD_HINT = 'fwd: queue'

export interface ControlItem {
  label: string
  gesture: string
  voice: string
}

/**
 * The Controls tab: a read-only reference of every gesture and its "verity" command. Swipes
 * switch tabs, so nothing here is picked; decline and revert are voice only, from any tab.
 */
export const CONTROLS: readonly ControlItem[] = [
  { label: 'Accept / done', gesture: 'tap', voice: 'verity accept/done' },
  { label: 'Clip last 2 min', gesture: 'swipe back', voice: 'verity clip' },
  { label: 'Hand off', gesture: 'hold', voice: 'verity handoff' },
  { label: 'Queue, Controls', gesture: 'swipe fwd', voice: 'verity queue/menu' },
  { label: 'Back to the card', gesture: 'hold', voice: 'verity back' },
  { label: 'Decline', gesture: 'voice', voice: 'verity decline' },
  { label: 'Revert last', gesture: 'voice', voice: 'verity revert' },
  { label: 'Set table', gesture: 'voice', voice: 'verity table N' },
  { label: 'Exit', gesture: 'double tap', voice: '-' },
]

export function controlRow(item: ControlItem, width = TAB_TEXT_WIDTH): string {
  return spread(`${item.label} (${item.gesture})`, item.voice, width)
}

/** Rows per Controls page; the last line is the footer. */
export const CONTROLS_PER_PAGE = CARD_MAX_LINES - 1
export const CONTROLS_PAGES = Math.ceil(CONTROLS.length / CONTROLS_PER_PAGE)

/** Right side of the Controls footer: tap flips the page, swipe back is the Queue tab. */
export const CONTROLS_FOOTER = 'tap: more · back: queue'

/** One page of the reference, then `n/N` and the footer. */
export function formatControls(page: number, width = TAB_TEXT_WIDTH): string {
  const p = ((page % CONTROLS_PAGES) + CONTROLS_PAGES) % CONTROLS_PAGES
  const rows = CONTROLS.slice(p * CONTROLS_PER_PAGE, (p + 1) * CONTROLS_PER_PAGE).map(item => controlRow(item, width))
  const pad = Array<string>(CONTROLS_PER_PAGE - rows.length).fill('')
  return [...rows, ...pad, spread(`${p + 1}/${CONTROLS_PAGES}`, CONTROLS_FOOTER, width)].join('\n')
}

/** A tap on Controls shows the next page, wrapping around. */
export function nextControlsPage(page: number): number {
  return (page + 1) % CONTROLS_PAGES
}
