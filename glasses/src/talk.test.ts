import { getTextWidth } from '@evenrealities/pretext'
import { describe, expect, it } from 'vitest'
import type { OrderDraft } from './contract'
import { DRAFT_TEXT_WIDTH } from './draft'
import { answerText, separator, talkLines, wrap } from './talk'

const W = DRAFT_TEXT_WIDTH

function draft(over: Partial<OrderDraft> = {}): OrderDraft {
  return { type: 'order.draft', orderId: 'o1', captureId: 'c1', table: 'T12', lines: [], allergies: [], ...over }
}

describe('talkLines', () => {
  it('is empty when the clip had no summary and no answers', () => {
    expect(talkLines(draft(), W)).toEqual([])
    expect(talkLines(draft({ summary: '  ', answers: [] }), W)).toEqual([])
    expect(talkLines(null, W)).toEqual([])
  })

  it('puts a separator, the summary, then one reply per question', () => {
    const lines = talkLines(
      draft({
        summary: 'Anniversary, relaxed',
        answers: [
          { seat: 2, q: 'risotto nuts?', a: 'no tree nuts listed for risotto', known: true },
          { q: "we're in a rush", a: "I'll fire mains right away" },
          { seat: 2, q: 'gluten-free bread?', a: 'not in menu data', known: false },
        ],
      }),
      W,
    )
    expect(lines[0].startsWith('── table said ─')).toBe(true)
    expect(lines.slice(1)).toEqual([
      'Anniversary, relaxed',
      's2 risotto nuts? → no tree nuts listed for risotto',
      "we're in a rush → I'll fire mains right away",
      '? s2 asks gluten-free bread: not in menu data',
    ])
  })

  it('wraps long lines by measured width, at most two lines each, indented', () => {
    const long = 'Celebrating a promotion tonight, very relaxed and chatty, want the mains to come slowly after a long pause and wine first please'
    const lines = talkLines(draft({ summary: long, answers: [{ seat: 1, q: 'can the torte come without nuts?', a: 'has tree nuts; menu allows: no whipped cream, no hazelnuts, extra sauce' }] }), W)
    expect(lines.length).toBe(5)
    for (const l of lines) expect(getTextWidth(l)).toBeLessThanOrEqual(W)
    expect(lines[2].endsWith('...')).toBe(true)
    expect(lines[4].startsWith('   ')).toBe(true)
  })
})

describe('talk helpers', () => {
  it('formats known and unknown answers', () => {
    expect(answerText({ q: 'duck spicy?', a: 'not in menu data', known: false })).toBe('? asks duck spicy: not in menu data')
    expect(answerText({ seat: 3, q: 'salmon fish?', a: 'yes, salmon has fish' })).toBe('s3 salmon fish? → yes, salmon has fish')
  })

  it('fills the separator to the width', () => {
    const s = separator(W)
    expect(getTextWidth(s)).toBeLessThanOrEqual(W)
    expect(getTextWidth(`${s}─`)).toBeGreaterThan(W)
  })

  it('wrap keeps a single word that is too wide on its own line', () => {
    expect(wrap('a'.repeat(200), 100, 2).length).toBe(1)
  })
})
