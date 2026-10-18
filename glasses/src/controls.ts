import { CARD_MAX_LINES, CARD_TEXT_WIDTH, spread } from './card'

// The gesture map in one place. MAIN_GESTURES is what each gesture does on the main card;
// giving swipe back (SDK `down`) to the queue instead of clip is `down: 'queue'`.
// On the G2 touchpad SDK `up` is a swipe fwd (toward the eyes) and `down` a swipe back (toward the ear). Double tap is always exit (Even Hub
// review rule) and lives in main.ts.

export type MainAction = 'task' | 'controls' | 'queue' | 'clip' | 'handoff'

export const MAIN_GESTURES: Record<'tap' | 'up' | 'down' | 'hold', MainAction> = {
  tap: 'task',
  up: 'controls',
  down: 'clip',
  hold: 'handoff',
}

/** Always on the main card, bottom right. */
export const CONTROLS_HINT = 'fwd: controls'

export type ControlAction = MainAction | 'decline' | 'revert' | 'exit' | 'close'

export interface ControlItem {
  label: string
  gesture: string
  voice: string
  action: ControlAction
}

const GESTURE_NAMES: Record<'tap' | 'up' | 'down' | 'hold', string> = {
  tap: 'tap',
  up: 'swipe fwd',
  down: 'swipe back',
  hold: 'hold',
}

function gestureFor(action: MainAction): string {
  const g = (Object.keys(MAIN_GESTURES) as (keyof typeof MAIN_GESTURES)[]).find(k => MAIN_GESTURES[k] === action)
  return g ? GESTURE_NAMES[g] : 'menu'
}

/** The Controls menu: every gesture and its "verity" command; a tap picks the selected row. */
export const CONTROLS: readonly ControlItem[] = [
  { label: 'Clip last minute', gesture: gestureFor('clip'), voice: 'verity clip', action: 'clip' },
  { label: 'Queue', gesture: gestureFor('queue'), voice: 'verity queue', action: 'queue' },
  { label: 'Accept / done', gesture: gestureFor('task'), voice: 'verity accept/done', action: 'task' },
  { label: 'Hand off', gesture: gestureFor('handoff'), voice: 'verity handoff', action: 'handoff' },
  { label: 'Decline', gesture: 'menu', voice: 'verity decline', action: 'decline' },
  { label: 'Revert last', gesture: 'menu', voice: 'verity revert', action: 'revert' },
  { label: 'Exit', gesture: 'double tap', voice: '-', action: 'exit' },
  { label: 'Close', gesture: 'hold', voice: 'verity back', action: 'close' },
]

export function controlRow(item: ControlItem, selected: boolean, width = CARD_TEXT_WIDTH): string {
  const left = `${selected ? '> ' : '  '}${item.label} (${item.gesture})`
  return spread(left, item.voice, width)
}

/** Last line of the Controls menu. */
export const CONTROLS_FOOTER = 'fwd/back: move · tap: pick · hold: back'

/** A window of rows that keeps the selected row on screen, then the footer. */
export function formatControls(selected: number, width = CARD_TEXT_WIDTH): string {
  const room = CARD_MAX_LINES - 1
  const start = Math.max(0, Math.min(selected - 2, CONTROLS.length - room))
  const rows = CONTROLS.slice(start, start + room).map((item, i) => controlRow(item, start + i === selected, width))
  return [...rows, spread('', CONTROLS_FOOTER, width)].join('\n')
}

/** Swipe fwd/back (SDK up/down) in the menu; it stops at the ends. Hold, Close or "verity back" close it. */
export function moveSelection(selected: number, dir: 'up' | 'down'): number {
  return dir === 'up' ? Math.max(0, selected - 1) : Math.min(CONTROLS.length - 1, selected + 1)
}
