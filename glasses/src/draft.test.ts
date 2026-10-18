import { getTextWidth } from '@evenrealities/pretext'
import { describe, expect, it } from 'vitest'
import type { OrderDraft } from './contract'
import { DRAFT_MAX_LINES, DRAFT_TEXT_WIDTH, closesDraft, draftGesture, formatDraft, orderLineText, type DraftState } from './draft'

function draft(over: Partial<OrderDraft> = {}): OrderDraft {
  return {
    type: 'order.draft',
    orderId: 'o1',
    captureId: 'c1',
    table: 'T12',
    lines: [
      { seat: 1, qty: 1, dish: 'halibut', alterations: ['no butter'], flagged: [] },
      { seat: 2, qty: 1, dish: 'salmon', alterations: ['no dill'], flagged: [] },
    ],
    allergies: [{ allergen: 'SHELLFISH', seats: [3] }],
    status: 'draft',
    pending: [],
    voice: 'listening',
    notice: null,
    ...over,
  }
}

const state = (over: Partial<DraftState> = {}): DraftState => ({
  draft: draft(),
  capturing: true,
  voice: 'listening',
  online: true,
  ...over,
})

describe('formatDraft', () => {
  it('pins allergies on top, then the table and Listening…, then the order by seat', () => {
    const lines = formatDraft(state()).main.split('\n')
    expect(lines[0]).toBe('! SHELLFISH s3')
    expect(lines[1].startsWith('T12')).toBe(true)
    expect(lines[1].endsWith('Listening…')).toBe(true)
    expect(lines.slice(2)).toEqual(['s1 halibut –no butter', 's2 salmon –no dill'])
  })

  it('shows the pending proposal highlighted in the bar', () => {
    const v = formatDraft(state({ draft: draft({ pending: [{ id: 'p1', action: 'remove', text: 'REMOVE s2 salmon?' }] }) }))
    expect(v.bar).toBe('REMOVE s2 salmon? tap=yes swipe up=no')
    expect(v.highlight).toBe(true)
  })

  it('shows VOICE OFFLINE and the refusal notice', () => {
    const v = formatDraft(state({ voice: 'offline', draft: draft({ notice: 's2 has no soup: nothing removed' }) }))
    const lines = v.main.split('\n')
    expect(lines[1].endsWith('VOICE OFFLINE')).toBe(true)
    expect(lines[2]).toBe('? s2 has no soup: nothing removed')
  })

  it('keeps every line within the measured width and line budget', () => {
    const many = Array.from({ length: 14 }, (_, i) => ({
      seat: i + 1,
      qty: 2,
      dish: 'pan-roasted halibut with a very long description',
      alterations: ['no butter', 'sauce on side'],
      flagged: ['extra truffle'],
    }))
    const lines = formatDraft(state({ draft: draft({ lines: many }) })).main.split('\n')
    expect(lines.length).toBe(DRAFT_MAX_LINES)
    for (const l of lines) expect(getTextWidth(l)).toBeLessThanOrEqual(DRAFT_TEXT_WIDTH)
    expect(lines[2]).toMatch(/^… \d+ more$/)
    expect(lines.at(-1)!.startsWith('s14')).toBe(true)
  })

  it('formats quantity and flagged alterations', () => {
    expect(orderLineText({ seat: 3, qty: 2, dish: 'ribeye', alterations: [], flagged: ['extra truffle'] })).toBe(
      's3 2× ribeye ?extra truffle',
    )
  })
})

describe('draftGesture', () => {
  const pending = (action: 'remove' | 'cancel' | 'confirm') => state({ draft: draft({ pending: [{ id: 'p7', action, text: 'x' }] }) })

  it('swipe down stops listening, or listens again when stopped', () => {
    expect(draftGesture('down', state()).then).toBe('stop')
    expect(draftGesture('down', state({ capturing: false })).then).toBe('listen')
  })

  it('tap accepts the pending proposal', () => {
    expect(draftGesture('tap', pending('remove')).send).toEqual({ type: 'order.confirm', orderId: 'o1', proposalId: 'p7' })
    expect(draftGesture('tap', pending('cancel')).send).toEqual({
      type: 'order.cancel_confirm',
      orderId: 'o1',
      proposalId: 'p7',
    })
  })

  it('tap with nothing pending confirms the whole order', () => {
    expect(draftGesture('tap', state()).send).toEqual({ type: 'order.confirm', orderId: 'o1' })
  })

  it('tap does nothing on an empty or already sent order', () => {
    expect(draftGesture('tap', state({ draft: draft({ lines: [] }) })).send).toBeNull()
    expect(draftGesture('tap', state({ draft: draft({ status: 'sent' }) })).send).toBeNull()
    expect(draftGesture('tap', state({ draft: null })).send).toBeNull()
  })

  it('swipe up rejects the pending proposal, else goes back keeping the draft', () => {
    expect(draftGesture('up', pending('remove'))).toEqual({
      send: { type: 'order.reject', orderId: 'o1', proposalId: 'p7' },
      then: 'none',
    })
    expect(draftGesture('up', state())).toEqual({ send: null, then: 'back' })
  })
})

describe('closesDraft', () => {
  const d = { type: 'order.draft', orderId: 'o1', captureId: 'c', table: 'T2', lines: [], allergies: [] } as const
  it('closes the matching draft, or when there is none', () => {
    expect(closesDraft({ ...d, lines: [] }, 'o1')).toBe(true)
    expect(closesDraft(null, 'o1')).toBe(true)
  })
  it('ignores another order closing', () => {
    expect(closesDraft({ ...d, lines: [] }, 'o2')).toBe(false)
  })
})
