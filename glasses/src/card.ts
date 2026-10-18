import { getTextWidth, pxTruncate } from '@evenrealities/pretext'
import type { Allergy, Task, TaskItem } from './contract'

export const DISPLAY_WIDTH = 576
export const DISPLAY_HEIGHT = 288
export const CARD_PADDING = 6
/** Inner text width of a full-width, borderless card. */
export const CARD_TEXT_WIDTH = DISPLAY_WIDTH - 2 * CARD_PADDING
export const CARD_MAX_LINES = 5

export interface CardView {
  text: string
  /** Text brightness 0..4: brightest when the card still needs a tap. */
  brightness: number
}

export interface CardOptions {
  offline: boolean
  width?: number
  maxLines?: number
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
  if (!head) return { text: opts.offline ? 'OFFLINE' : '', brightness: 4 }

  const lines: string[] = []
  const allergies = allergyLine(head.allergies)
  if (allergies) lines.push(fit(allergies, width))
  lines.push(fit(taskLine(head), width))

  const status = [head.state === 'accepted' ? 'ACCEPTED' : '', opts.offline ? 'OFFLINE' : '']
    .filter(Boolean)
    .join(' · ')
  const queued = queue.length > 1 ? `+${queue.length - 1} queued` : ''
  const footer = status || queued ? spread(status, queued, width) : ''

  const noteRoom = maxLines - lines.length - (footer ? 1 : 0)
  for (const note of head.notes.slice(0, Math.max(0, noteRoom))) lines.push(fit(note, width))
  if (footer) lines.push(footer)

  return { text: lines.join('\n'), brightness: head.state === 'assigned' ? 4 : 2 }
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

/** One row of the queue list screen: allergies first, like the card. */
export function queueRow(task: Task, width: number): string {
  const allergy = task.allergies.length ? `! ${task.allergies.map(a => a.allergen.toUpperCase()).join(',')} ` : ''
  return fitBytes(fit(`${allergy}${taskLine(task)}`, width), LIST_ITEM_MAX_BYTES)
}
