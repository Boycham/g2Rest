import { CARD_MAX_LINES, CARD_TEXT_WIDTH, spread } from './card'

// The gesture map in one place. MAIN_GESTURES is what each gesture does on the main card;
// giving swipe down to the queue instead of clip is `down: 'queue'`. Double tap is always exit (Even Hub
// review rule) and lives in main.ts.

export type MainAction = 'task' | 'controls' | 'queue' | 'clip' | 'handoff'

export const MAIN_GESTURES: Record<'tap' | 'up' | 'down' | 'hold', MainAction> = {
  tap: 'task',
  up: 'controls',
  down: 'clip',
  hold: 'handoff',
}

/** Always on the main card, bottom right. */
export const CONTROLS_HINT = '↑ controls'

export type ControlAction = MainAction | 'decline' | 'revert' | 'table' | 'exit' | 'close'

export interface ControlItem {
  label: string
  gesture: string
  voice: string
  action: ControlAction
}

const GESTURE_NAMES: Record<'tap' | 'up' | 'down' | 'hold', string> = {
  tap: 'tap',
  up: 'swipe up',
  down: 'swipe down',
  hold: 'hold',
}

function gestureFor(action: MainAction): string {
  const g = (Object.keys(MAIN_GESTURES) as (keyof typeof MAIN_GESTURES)[]).find(k => MAIN_GESTURES[k] === action)
  return g ? GESTURE_NAMES[g] : 'menu'
}

/** The Controls menu: every gesture and its "verity" command; a tap picks the selected row. */
export const CONTROLS: readonly ControlItem[] = [
  { label: 'Clip last 2 min', gesture: gestureFor('clip'), voice: 'verity clip', action: 'clip' },
  { label: 'Queue', gesture: gestureFor('queue'), voice: 'verity queue', action: 'queue' },
  { label: 'Accept / done', gesture: gestureFor('task'), voice: 'verity accept/done', action: 'task' },
  { label: 'Hand off', gesture: gestureFor('handoff'), voice: 'verity handoff', action: 'handoff' },
  { label: 'Decline', gesture: 'menu', voice: 'verity decline', action: 'decline' },
  { label: 'Revert last', gesture: 'menu', voice: 'verity revert', action: 'revert' },
  { label: 'Set table', gesture: 'voice', voice: 'verity table N', action: 'table' },
  { label: 'Exit', gesture: 'double tap', voice: '-', action: 'exit' },
  { label: 'Close', gesture: 'menu', voice: 'verity back', action: 'close' },
]

export function controlRow(item: ControlItem, selected: boolean, width = CARD_TEXT_WIDTH): string {
  const left = `${selected ? '> ' : '  '}${item.label} (${item.gesture})`
  return spread(left, item.voice, width)
}

/** A window of CARD_MAX_LINES rows that keeps the selected row on screen. */
export function formatControls(selected: number, width = CARD_TEXT_WIDTH): string {
  const start = Math.max(0, Math.min(selected - 2, CONTROLS.length - CARD_MAX_LINES))
  return CONTROLS.slice(start, start + CARD_MAX_LINES)
    .map((item, i) => controlRow(item, start + i === selected, width))
    .join('\n')
}

/** Swipe up/down in the menu; it stops at the ends. Only "verity back" or Close closes it. */
export function moveSelection(selected: number, dir: 'up' | 'down'): number {
  return dir === 'up' ? Math.max(0, selected - 1) : Math.min(CONTROLS.length - 1, selected + 1)
}
