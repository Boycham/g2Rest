import type { GlassesJsonMessage, OrderDraft, OrderLine, VoiceState } from './contract'
import { allergyLine, CARD_PADDING, DISPLAY_HEIGHT, DISPLAY_WIDTH, fit, spread } from './card'
import { talkLines } from './talk'

// The order-draft screen: what the backend made of the last 2 minutes, by seat, with allergies
// pinned on top, ? lines for anything unclear, and one highlighted pending line for a change
// that needs a tap. Pure, so layout and gestures are tested.

export const LINE_PX = 27
export const BAR_HEIGHT = LINE_PX + 2 * CARD_PADDING + 4
export const DRAFT_HEIGHT = DISPLAY_HEIGHT - BAR_HEIGHT
export const DRAFT_TEXT_WIDTH = DISPLAY_WIDTH - 2 * CARD_PADDING
export const DRAFT_MAX_LINES = Math.floor((DRAFT_HEIGHT - 2 * CARD_PADDING) / LINE_PX)
/** Order text is dimmed while a pending line waits, so the pending line stands out. */
export const DIM = 2
export const BRIGHT = 4

export interface DraftState {
  draft: OrderDraft | null
  voice: VoiceState
  online: boolean
  /** A line written on the glasses (e.g. "mic off: nothing recorded"), shown when the draft has no notice. */
  hint?: string | null
  /** Page of the draft on screen (swipe fwd turns it when the table's talk overflows). */
  page?: number
  /** The animated `Verity: processing...` / `summary...` line, alone in the bar container. */
  busy?: string | null
}

export interface DraftView {
  main: string
  bar: string
  /** Pages the draft spans: the order and as much of the table's talk as fits, then the rest. */
  pages: number
  /** True while a pending proposal is shown: main is dimmed, bar is bright. */
  highlight: boolean
}

export const NO_TABLE = 'TABLE?'

export function orderLineText(l: OrderLine): string {
  const dish = l.qty > 1 ? `${l.qty}× ${l.dish}` : l.dish
  return [`s${l.seat}`, dish, ...l.alterations.map(a => `–${a}`), ...l.flagged.map(f => `?${f}`)].join(' ')
}

export function statusLabel(s: DraftState): string {
  if (!s.online) return 'OFFLINE'
  if (s.voice === 'offline') return 'VOICE OFFLINE'
  const status = s.draft?.status
  if (status === 'sent') return 'SENT'
  if (status === 'cancelled') return 'CANCELLED'
  if (s.voice === 'processing' || s.voice === 'connecting') return 'Reading last 2 min…'
  return s.draft?.lines.length && s.draft.table ? 'tap = send' : ''
}

/**
 * Allergies on top, then the table (TABLE? until it is known) and status, a notice, the order
 * by seat, then the ? lines and notes. Order lines are the ones folded into "… N more" when
 * space runs out, so an unclear item is never pushed off the lens.
 */
export function formatDraft(s: DraftState, width = DRAFT_TEXT_WIDTH, maxLines = DRAFT_MAX_LINES): DraftView {
  const d = s.draft
  const head: string[] = []
  const allergies = d ? allergyLine(d.allergies) : ''
  if (allergies) head.push(fit(allergies, width))
  head.push(spread(d ? (d.table ?? NO_TABLE) : 'Last 2 min', statusLabel(s), width))
  const notice = d?.notice ?? s.hint
  if (notice) head.push(fit(`? ${notice}`, width))
  const tail = (d?.uncertain ?? []).map(u => fit(u, width))
  if (d?.notes?.length) tail.push(fit(`note: ${d.notes.join(' · ')}`, width))
  const room = Math.max(1, maxLines - head.length - tail.length)
  let lines = (d?.lines ?? []).map(l => fit(orderLineText(l), width))
  if (lines.length > room) {
    const hidden = lines.length - room + 1
    lines = [`… ${hidden} more`, ...lines.slice(hidden)]
  }
  const first = [...head, ...lines, ...tail].slice(0, maxLines)
  const pages = paginate(first, talkLines(d, width), head.at(-1) ?? '', maxLines)
  const page = Math.min(s.page ?? 0, pages.length - 1)
  const body = pages[page]
  const pending = d?.pending ?? []
  let bar = ''
  if (pending.length) {
    bar = fit(`${pending[0].text} tap=yes swipe fwd=no${pending.length > 1 ? ` +${pending.length - 1}` : ''}`, width)
  } else if (d?.lines.length && !d.table && (d.status ?? 'draft') === 'draft') {
    const of = pages.length > 1 ? ` · fwd ${page + 1}/${pages.length}` : ''
    bar = fit(`${NO_TABLE} say the table, then swipe back${of}`, width)
  } else if (pages.length > 1) {
    bar = fit(page < pages.length - 1 ? `swipe fwd = more ${page + 1}/${pages.length}` : `${page + 1}/${pages.length} swipe fwd = done`, width)
  }
  if (s.busy) bar = bar ? spread(bar, s.busy, width) : fit(s.busy, width)
  return { main: body.join('\n'), bar, highlight: pending.length > 0, pages: pages.length }
}

/** The order page, then the table's talk filling what is left of it and further pages, each under the table line. */
function paginate(first: string[], talk: string[], title: string, maxLines: number): string[][] {
  const pages = [[...first]]
  let rest = talk
  const room = maxLines - first.length
  // A separator alone at the foot of the order page reads as nothing: start the talk on a fresh page.
  if (room >= 2) {
    pages[0].push(...rest.slice(0, room))
    rest = rest.slice(room)
  }
  while (rest.length) {
    const per = Math.max(1, maxLines - 1)
    pages.push([title, ...rest.slice(0, per)])
    rest = rest.slice(per)
  }
  return pages
}

export type Gesture = 'tap' | 'up' | 'down'

export interface DraftAction {
  send: GlassesJsonMessage | null
  then: 'none' | 'clip' | 'back' | 'page'
}

/**
 * Swipe back (SDK down): send the last 2 minutes again (more ordering, or the spoken table). Tap: accept the
 * pending proposal, else send the whole order, which needs a table. Swipe fwd (SDK up): reject the
 * pending proposal, else back to the card.
 */
export function draftGesture(g: Gesture, s: DraftState): DraftAction {
  const d = s.draft
  const pending = d?.pending?.[0]
  if (g === 'down') return { send: null, then: 'clip' }
  if (g === 'up') {
    if (d && pending) return { send: { type: 'order.reject', orderId: d.orderId, proposalId: pending.id }, then: 'none' }
    const v = formatDraft(s)
    if ((s.page ?? 0) < v.pages - 1) return { send: null, then: 'page' }
    return { send: null, then: 'back' }
  }
  if (!d || !d.orderId) return { send: null, then: 'none' }
  if (pending) {
    const type = pending.action === 'cancel' ? 'order.cancel_confirm' : 'order.confirm'
    return { send: { type, orderId: d.orderId, proposalId: pending.id }, then: 'none' }
  }
  if (d.lines.length && d.table && (d.status ?? 'draft') === 'draft') {
    return { send: { type: 'order.confirm', orderId: d.orderId }, then: 'none' }
  }
  return { send: null, then: 'none' }
}

/** `order.closed` ends the draft on screen: same order, or no draft yet (the hub's own order id). */
export function closesDraft(draft: OrderDraft | null, closedOrderId: string): boolean {
  return draft === null || draft.orderId === '' || draft.orderId === closedOrderId
}
