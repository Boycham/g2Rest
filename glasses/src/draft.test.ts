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
  voice: 'idle',
  online: true,
  ...over,
})

describe('formatDraft', () => {
  it('pins allergies on top, then the table and tap = send, then the order by seat', () => {
    const lines = formatDraft(state()).main.split('\n')
    expect(lines[0]).toBe('! SHELLFISH s3')
    expect(lines[1].startsWith('T12')).toBe(true)
    expect(lines[1].endsWith('tap = send')).toBe(true)
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

  it('swipe down sends the last 2 minutes again', () => {
    expect(draftGesture('down', state())).toEqual({ send: null, then: 'clip' })
  })

  it('tap does not send a draft whose table is unknown', () => {
    expect(draftGesture('tap', state({ draft: draft({ table: null }) })).send).toBeNull()
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

describe('formatDraft for a clip', () => {
  it('shows Reading last 2 min… while the clip is processed', () => {
    const lines = formatDraft(state({ draft: null, voice: 'processing' })).main.split('\n')
    expect(lines[0].startsWith('Last 2 min')).toBe(true)
    expect(lines[0].endsWith('Reading last 2 min…')).toBe(true)
  })

  it('shows TABLE? and how to give it when the draft has no table', () => {
    const v = formatDraft(state({ draft: draft({ table: null }) }))
    expect(v.main.split('\n')[1].startsWith('TABLE?')).toBe(true)
    expect(v.bar).toBe('TABLE? say the table, then swipe down')
    expect(v.highlight).toBe(false)
  })

  it('keeps ? lines and notes on screen when order lines overflow', () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ seat: i + 1, qty: 1, dish: 'soup', alterations: [], flagged: [] }))
    const v = formatDraft(
      state({ draft: draft({ lines: many, uncertain: ["? s3 'the fish': halibut or salmon"], notes: ['anniversary'] }) }),
    )
    const lines = v.main.split('\n')
    expect(lines.length).toBe(DRAFT_MAX_LINES)
    expect(lines.at(-2)).toBe("? s3 'the fish': halibut or salmon")
    expect(lines.at(-1)).toBe('note: anniversary')
    expect(lines.some(l => /^… \d+ more$/.test(l))).toBe(true)
  })

  it('shows a glasses-written hint when there is nothing to send', () => {
    const lines = formatDraft(state({ draft: null, hint: 'mic off: nothing recorded' })).main.split('\n')
    expect(lines[1]).toBe('? mic off: nothing recorded')
  })
})

describe('closesDraft', () => {
  const d: OrderDraft = { type: 'order.draft', orderId: 'o1', captureId: 'c', table: 'T2', lines: [], allergies: [] }
  it('closes the matching draft, or when there is none', () => {
    expect(closesDraft(d, 'o1')).toBe(true)
    expect(closesDraft(null, 'o1')).toBe(true)
  })
  it('ignores another order closing', () => {
    expect(closesDraft(d, 'o2')).toBe(false)
  })
})

describe('formatDraft with the table talk', () => {
  const answers = [
    { seat: 2, q: 'risotto nuts?', a: 'no tree nuts listed for risotto', known: true },
    { seat: 2, q: 'risotto vegetarian?', a: 'not in menu data', known: false },
    { q: "we're in a rush", a: "I'll fire mains right away" },
  ]

  it('shows the order first, then the separator, summary and answers', () => {
    const v = formatDraft(state({ draft: draft({ summary: 'Anniversary, in a rush', answers: answers.slice(0, 1) }) }))
    const lines = v.main.split('\n')
    expect(lines.slice(2, 4)).toEqual(['s1 halibut –no butter', 's2 salmon –no dill'])
    expect(lines[4].startsWith('── table said')).toBe(true)
    expect(lines.slice(5)).toEqual(['Anniversary, in a rush', 's2 risotto nuts? → no tree nuts listed for risotto'])
    expect(v.pages).toBe(1)
  })

  it('shows summary and answers with no order and nothing to send', () => {
    const d = draft({ table: null, lines: [], allergies: [], summary: 'Just browsing, in a rush', answers })
    const v = formatDraft(state({ draft: d }))
    const lines = v.main.split('\n')
    expect(lines[0]).toBe('TABLE?')
    expect(lines[1].startsWith('── table said')).toBe(true)
    expect(lines.at(-1)).toBe("we're in a rush → I'll fire mains right away")
    expect(v.bar).toBe('')
    expect(draftGesture('tap', state({ draft: d }))).toEqual({ send: null, then: 'none' })
  })

  it('pages the talk when it does not fit, and swipe fwd turns the page, then goes back', () => {
    const many = Array.from({ length: 5 }, (_, i) => ({ seat: i + 1, qty: 1, dish: 'soup', alterations: [], flagged: [] }))
    const d = draft({ lines: many, summary: 'Birthday at seat 3, relaxed', answers })
    const p0 = formatDraft(state({ draft: d }))
    expect(p0.pages).toBe(2)
    expect(p0.bar).toBe('swipe fwd = more 1/2')
    expect(p0.main.split('\n').length).toBeLessThanOrEqual(DRAFT_MAX_LINES)
    expect(draftGesture('up', state({ draft: d }))).toEqual({ send: null, then: 'page' })
    const p1 = formatDraft(state({ draft: d, page: 1 }))
    const lines = p1.main.split('\n')
    expect(lines[0].startsWith('T12')).toBe(true)
    expect(lines.slice(1).some(l => l.startsWith('? s2 asks risotto vegetarian'))).toBe(true)
    expect(p1.bar).toBe('2/2 swipe fwd = done')
    for (const l of lines) expect(getTextWidth(l)).toBeLessThanOrEqual(DRAFT_TEXT_WIDTH)
    expect(draftGesture('up', state({ draft: d, page: 1 }))).toEqual({ send: null, then: 'back' })
  })

  it('keeps the page count in the TABLE? bar so the rest of the talk is not hidden', () => {
    const many = Array.from({ length: 5 }, (_, i) => ({ seat: i + 1, qty: 1, dish: 'soup', alterations: [], flagged: [] }))
    const d = draft({ table: null, lines: many, summary: 'Birthday at seat 3, relaxed', answers })
    expect(formatDraft(state({ draft: d })).bar).toBe('TABLE? say the table, then swipe down · fwd 1/2')
    expect(formatDraft(state({ draft: d, page: 1 })).bar).toBe('TABLE? say the table, then swipe down · fwd 2/2')
  })

  it('a tap sends only the order: the summary and answers are not in the message', () => {
    const a = draftGesture('tap', state({ draft: draft({ summary: 'Anniversary', answers }) }))
    expect(a.send).toEqual({ type: 'order.confirm', orderId: 'o1' })
  })

  it('a pending proposal still wins the bar and swipe fwd over paging', () => {
    const many = Array.from({ length: 6 }, (_, i) => ({ seat: i + 1, qty: 1, dish: 'soup', alterations: [], flagged: [] }))
    const d = draft({ lines: many, answers, pending: [{ id: 'p1', action: 'remove', text: 'REMOVE s2 soup?' }] })
    expect(formatDraft(state({ draft: d })).bar.startsWith('REMOVE s2 soup?')).toBe(true)
    expect(draftGesture('up', state({ draft: d }))).toEqual({ send: { type: 'order.reject', orderId: 'o1', proposalId: 'p1' }, then: 'none' })
  })
})
