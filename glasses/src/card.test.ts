import { describe, expect, it } from 'vitest'
import { getTextWidth } from '@evenrealities/pretext'
import { CARD_MAX_LINES, CARD_TEXT_WIDTH, fitBytes, formatCard, formatQueue, queueRow, taskLine } from './card'
import { makeTask } from './fixtures.test-helpers'

const lines = (text: string) => text.split('\n')

describe('formatCard', () => {
  it('is blank when the queue is empty', () => {
    expect(formatCard([], { offline: false }).text).toBe('')
  })

  it('shows OFFLINE even with an empty queue', () => {
    expect(formatCard([], { offline: true }).text).toBe('OFFLINE')
  })

  it('formats the task line', () => {
    expect(taskLine(makeTask())).toBe('RUN · T12 · 2× halibut s1+3')
    expect(formatCard([makeTask()], { offline: false }).text).toBe('RUN · T12 · 2× halibut s1+3')
  })

  it('puts allergies on the top line, above the task', () => {
    const task = makeTask({ allergies: [{ allergen: 'shellfish', seats: [3] }], notes: ['VIP: anniversary'] })
    const l = lines(formatCard([task], { offline: false }).text)
    expect(l[0]).toBe('! SHELLFISH s3')
    expect(l[1]).toBe('RUN · T12 · 2× halibut s1+3')
    expect(l[2]).toBe('VIP: anniversary')
  })

  it('joins several allergies on the one top line', () => {
    const task = makeTask({
      allergies: [
        { allergen: 'SHELLFISH', seats: [3] },
        { allergen: 'NUTS', seats: [] },
      ],
    })
    expect(lines(formatCard([task], { offline: false }).text)[0]).toBe('! SHELLFISH s3 · NUTS')
  })

  it('shows +N queued flush right on the last line', () => {
    const q = [makeTask({ id: 'a' }), makeTask({ id: 'b' }), makeTask({ id: 'c' })]
    const last = lines(formatCard(q, { offline: false }).text).at(-1)!
    expect(last.trimStart()).toBe('+2 queued')
    expect(last.endsWith('+2 queued')).toBe(true)
    expect(getTextWidth(last)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    expect(getTextWidth(last)).toBeGreaterThan(CARD_TEXT_WIDTH - getTextWidth('  '))
  })

  it('has no queued marker for a single task', () => {
    expect(formatCard([makeTask()], { offline: false }).text).not.toContain('queued')
  })

  it('marks accepted and offline on the footer, dimmer once accepted', () => {
    const q = [makeTask({ state: 'accepted' }), makeTask({ id: 'b' })]
    const view = formatCard(q, { offline: true })
    const last = lines(view.text).at(-1)!
    expect(last.startsWith('ACCEPTED · OFFLINE')).toBe(true)
    expect(last.endsWith('+1 queued')).toBe(true)
    expect(view.brightness).toBeLessThan(formatCard([makeTask()], { offline: false }).brightness)
  })

  it('truncates long lines to the card width instead of wrapping', () => {
    const task = makeTask({
      items: Array.from({ length: 8 }, (_, i) => ({ qty: 1, dish: `wagyu tasting course ${i}`, seats: [i + 1] })),
      allergies: [{ allergen: 'SHELLFISH AND EVERY OTHER CRUSTACEAN KNOWN TO SCIENCE', seats: [1, 2, 3, 4] }],
      notes: ['n'.repeat(300)],
    })
    const l = lines(formatCard([task, makeTask({ id: 'b' })], { offline: false }).text)
    for (const line of l) expect(getTextWidth(line)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    expect(l[0].startsWith('! SHELLFISH')).toBe(true)
    expect(l[0].endsWith('...')).toBe(true)
    expect(l[1].endsWith('...')).toBe(true)
  })

  it('caps the card at the line limit, dropping notes before the footer', () => {
    const task = makeTask({
      allergies: [{ allergen: 'NUTS', seats: [1] }],
      notes: ['one', 'two', 'three', 'four'],
    })
    const l = lines(formatCard([task, makeTask({ id: 'b' })], { offline: false, maxLines: 4 }).text)
    expect(l).toHaveLength(4)
    expect(l[0]).toBe('! NUTS s1')
    expect(l[2]).toBe('one')
    expect(l[3].endsWith('+1 queued')).toBe(true)
  })
})

describe('queueRow', () => {
  it('leads with the allergy and fits the list byte limit', () => {
    const row = queueRow(
      makeTask({ allergies: [{ allergen: 'shellfish', seats: [3] }], items: [{ qty: 2, dish: 'halibut '.repeat(10), seats: [1] }] }),
      CARD_TEXT_WIDTH,
    )
    expect(row.startsWith('! SHELLFISH RUN · T12')).toBe(true)
    expect(new TextEncoder().encode(row).length).toBeLessThanOrEqual(63)
  })

  it('fitBytes leaves short text alone and never splits a character', () => {
    expect(fitBytes('abc', 63)).toBe('abc')
    const out = fitBytes('×'.repeat(40), 63)
    expect(new TextEncoder().encode(out).length).toBeLessThanOrEqual(63)
    expect(out.endsWith('...')).toBe(true)
  })
})

describe('formatQueue', () => {
  it('says the queue is empty', () => {
    expect(formatQueue([])).toBe('Queue empty')
  })

  it('lists every task, the current one marked, allergies first', () => {
    const q = [
      makeTask({ id: 'a', allergies: [{ allergen: 'shellfish', seats: [3] }] }),
      makeTask({ id: 'b', kind: 'CLEAR', table: 'T7', items: [] }),
    ]
    expect(lines(formatQueue(q))).toEqual(['> ! SHELLFISH RUN · T12 · 2× halibut s1+3', '  CLEAR · T7'])
  })

  it('caps the screen and counts the rest', () => {
    const q = Array.from({ length: 9 }, (_, i) => makeTask({ id: `t${i}` }))
    const l = lines(formatQueue(q))
    expect(l).toHaveLength(CARD_MAX_LINES)
    expect(l[CARD_MAX_LINES - 1]).toBe(`  +${9 - (CARD_MAX_LINES - 1)} more`)
    for (const line of l) expect(getTextWidth(line)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
  })
})
