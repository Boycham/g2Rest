import type { GlassesJsonMessage, OrderDraft, OrderLine, VoiceState } from './contract'
import { allergyLine, CARD_PADDING, DISPLAY_HEIGHT, DISPLAY_WIDTH, fit, spread } from './card'

// The order-draft screen: order by seat with allergies pinned on top, and one highlighted
// pending line for a change that needs a tap. Pure, so layout and gestures are tested.

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
  capturing: boolean
  voice: VoiceState
  online: boolean
}

export interface DraftView {
  main: string
  bar: string
  /** True while a pending proposal is shown: main is dimmed, bar is bright. */
  highlight: boolean
}

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
  if (!s.capturing) return 'paused'
  return s.voice === 'connecting' ? 'Connecting…' : 'Listening…'
}

export function formatDraft(s: DraftState, width = DRAFT_TEXT_WIDTH, maxLines = DRAFT_MAX_LINES): DraftView {
  const d = s.draft
  const head: string[] = []
  const allergies = d ? allergyLine(d.allergies) : ''
  if (allergies) head.push(fit(allergies, width))
  head.push(spread(d?.table ?? 'New order', statusLabel(s), width))
  if (d?.notice) head.push(fit(`? ${d.notice}`, width))
  let lines = (d?.lines ?? []).map(l => fit(orderLineText(l), width))
  const room = Math.max(1, maxLines - head.length)
  if (lines.length > room) {
    const hidden = lines.length - room + 1
    lines = [`… ${hidden} more`, ...lines.slice(hidden)]
  }
  const pending = d?.pending ?? []
  const bar = pending.length
    ? fit(`${pending[0].text} tap=yes swipe up=no${pending.length > 1 ? ` +${pending.length - 1}` : ''}`, width)
    : ''
  return { main: [...head, ...lines].join('\n'), bar, highlight: pending.length > 0 }
}

export type Gesture = 'tap' | 'up' | 'down'

export interface DraftAction {
  send: GlassesJsonMessage | null
  then: 'none' | 'stop' | 'listen' | 'back'
}

/**
 * Swipe down: stop listening (or listen again). Tap: accept the pending proposal, else
 * send the whole order. Swipe up: reject the pending proposal, else back to the card.
 */
export function draftGesture(g: Gesture, s: DraftState): DraftAction {
  const d = s.draft
  const pending = d?.pending?.[0]
  if (g === 'down') return { send: null, then: s.capturing ? 'stop' : 'listen' }
  if (g === 'up') {
    if (d && pending) return { send: { type: 'order.reject', orderId: d.orderId, proposalId: pending.id }, then: 'none' }
    return { send: null, then: 'back' }
  }
  if (!d || !d.orderId) return { send: null, then: 'none' }
  if (pending) {
    const type = pending.action === 'cancel' ? 'order.cancel_confirm' : 'order.confirm'
    return { send: { type, orderId: d.orderId, proposalId: pending.id }, then: 'none' }
  }
  if (d.lines.length && (d.status ?? 'draft') === 'draft') {
    return { send: { type: 'order.confirm', orderId: d.orderId }, then: 'none' }
  }
  return { send: null, then: 'none' }
}

/** `order.closed` ends the draft on screen: same order, or no draft yet (the hub's own order id). */
export function closesDraft(draft: OrderDraft | null, closedOrderId: string): boolean {
  return draft === null || draft.orderId === '' || draft.orderId === closedOrderId
}
