import { getTextWidth, pxTruncate } from '@evenrealities/pretext'
import type { Allergy, Task, TaskItem } from './contract'

export const DISPLAY_WIDTH = 576
export const DISPLAY_HEIGHT = 288
export const CARD_PADDING = 6
/** Inner text width of a full-width, borderless card. */
export const CARD_TEXT_WIDTH = DISPLAY_WIDTH - 2 * CARD_PADDING
export const CARD_MAX_LINES = 5
/** The tab rail on the left of the server tabs: one box per tab, wide enough for `Controls`. */
export const TAB_RAIL_WIDTH = 88
/** Inner text width of the content beside the tab rail. */
export const TAB_TEXT_WIDTH = DISPLAY_WIDTH - TAB_RAIL_WIDTH - 2 * CARD_PADDING

/** Shown under an accepted ORDER task: the table is bound, the clip does the rest. */
export const ORDER_HINT = 'swipe back once they have ordered'

export interface CardView {
  text: string
  /** Text brightness 0..4: brightest when the card still needs a tap. */
  brightness: number
}

export interface CardOptions {
  offline: boolean
  width?: number
  maxLines?: number
  /** A transient line under the allergies, e.g. `Heard: accept`. */
  banner?: string
  /** What is 86'd tonight (`eightysix.ts`), under the allergies until un-86'd, e.g. `86 halibut`. */
  eightySix?: string
  /** Always-on corner hint (bottom right), e.g. `fwd: controls`. */
  hint?: string
}

export function seatsLabel(seats: readonly number[]): string {
  return seats.length ? `s${seats.join('+')}` : ''
}

function withSeats(label: string, seats: readonly number[]): string {
  const s = seatsLabel(seats)
  return s ? `${label} ${s}` : label
}

export function allergyLine(allergies: readonly Allergy[]): string {
  if (!allergies.length) return ''
  return '! ' + allergies.map(a => withSeats(a.allergen.toUpperCase(), a.seats)).join(' · ')
}

function itemLabel(item: TaskItem): string {
  return withSeats(`${item.qty}× ${item.dish}`, item.seats)
}

export function taskLine(task: Task): string {
  const parts: string[] = [task.kind, task.table]
  if (task.items.length) parts.push(task.items.map(itemLabel).join(', '))
  return parts.join(' · ')
}

export function fit(text: string, width: number): string {
  return getTextWidth(text) <= width ? text : pxTruncate(text, width)
}

/** `left` flush left and `right` flush right on one line, padded with spaces. */
export function spread(left: string, right: string, width: number): string {
  if (!right) return fit(left, width)
  const rightW = getTextWidth(right)
  const gap = getTextWidth(' ')
  const l = left ? fit(left, width - rightW - gap) : ''
  const spaces = Math.max(1, Math.floor((width - getTextWidth(l) - rightW) / gap))
  return l + ' '.repeat(spaces) + right
}

export function formatCard(queue: readonly Task[], opts: CardOptions): CardView {
  const width = opts.width ?? CARD_TEXT_WIDTH
  const maxLines = opts.maxLines ?? CARD_MAX_LINES
  const head = queue[0]
  if (!head) {
    const top = opts.banner ? fit(opts.banner, width) : opts.offline ? 'OFFLINE' : ''
    const out = opts.eightySix ? [fit(opts.eightySix, width)] : []
    const shown = top || !out.length ? [...out, top] : out
    if (!opts.hint) return { text: shown.join('\n'), brightness: top ? 4 : out.length ? 2 : 4 }
    return { text: atBottom(shown, spread('', opts.hint, width), maxLines), brightness: 2 }
  }

  const lines: string[] = []
  const allergies = allergyLine(head.allergies)
  if (allergies) lines.push(fit(allergies, width))
  if (opts.eightySix) lines.push(fit(opts.eightySix, width))
  if (opts.banner) lines.push(fit(opts.banner, width))
  lines.push(fit(taskLine(head), width))

  const status = [head.state === 'accepted' ? 'ACCEPTED' : '', opts.offline ? 'OFFLINE' : '']
    .filter(Boolean)
    .join(' · ')
  const queued = queue.length > 1 ? `+${queue.length - 1} queued` : ''
  const right = [queued, opts.hint ?? ''].filter(Boolean).join(' · ')
  const footer = status || right ? spread(status, right, width) : ''

  const notes = head.kind === 'ORDER' && head.state === 'accepted' ? [...head.notes, ORDER_HINT] : head.notes
  const noteRoom = maxLines - lines.length - (footer ? 1 : 0)
  for (const note of notes.slice(0, Math.max(0, noteRoom))) lines.push(fit(note, width))
  const brightness = head.state === 'assigned' ? 4 : 2
  if (opts.hint) return { text: atBottom(lines, footer, maxLines), brightness }
  if (footer) lines.push(footer)
  return { text: lines.join('\n'), brightness }
}

/** `footer` on the last line, so the corner hint sits bottom right under the card text. */
function atBottom(lines: readonly string[], footer: string, maxLines: number): string {
  const pad = Math.max(0, maxLines - 1 - lines.length)
  return [...lines, ...Array<string>(pad).fill(''), footer].join('\n')
}

/** List items are capped by bytes (63 in the simulator), not pixels. */
export const LIST_ITEM_MAX_BYTES = 63

export function fitBytes(text: string, maxBytes: number): string {
  const enc = new TextEncoder()
  if (enc.encode(text).length <= maxBytes) return text
  let out = ''
  for (const ch of text) {
    if (enc.encode(out + ch + '...').length > maxBytes) break
    out += ch
  }
  return out + '...'
}

/** Bottom right of the Queue tab: Controls is the tab above it. */
export const QUEUE_FOOTER = 'fwd: controls'

/** One row of the queue screen: table and kind, then any allergy. No dishes; the card has those. */
export function queueRow(task: Task, width: number): string {
  const allergy = task.allergies.length ? ` · ! ${task.allergies.map(a => a.allergen.toUpperCase()).join(',')}` : ''
  return fitBytes(fit(`${task.table} · ${task.kind}${allergy}`, width), LIST_ITEM_MAX_BYTES)
}

/**
 * The Queue tab, as text in one container: one row per task, the current one marked, and
 * `fwd: controls` on the last line. A list container would swallow swipes (the firmware moves the
 * selection instead of sending us the event), so the queue is plain text.
 */
export function formatQueue(queue: readonly Task[], width = TAB_TEXT_WIDTH): string {
  const footer = spread('', QUEUE_FOOTER, width)
  if (!queue.length) return atBottom(['Queue empty'], footer, CARD_MAX_LINES)
  const room = CARD_MAX_LINES - 1
  const rows = queue.map((t, i) => (i === 0 ? '> ' : '  ') + queueRow(t, width - getTextWidth('> ')))
  const shown = rows.length <= room ? rows : [...rows.slice(0, room - 1), `  +${queue.length - (room - 1)} more`]
  return atBottom(shown, footer, CARD_MAX_LINES)
}
