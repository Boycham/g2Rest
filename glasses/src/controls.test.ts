import { getTextWidth } from '@evenrealities/pretext'
import { describe, expect, it } from 'vitest'
import { CARD_MAX_LINES, CARD_TEXT_WIDTH, formatCard } from './card'
import { CONTROLS, CONTROLS_FOOTER, CONTROLS_HINT, MAIN_GESTURES, controlRow, formatControls, moveSelection } from './controls'
import { makeTask } from './fixtures.test-helpers'

describe('gesture map', () => {
  it('keeps clip on swipe back (SDK down) and the queue in the menu', () => {
    expect(MAIN_GESTURES).toEqual({ tap: 'task', up: 'controls', down: 'clip', hold: 'handoff' })
    expect(CONTROLS.map(c => c.action)).toContain('queue')
    expect(CONTROLS.at(-1)?.action).toBe('close')
  })

  it('lists Set table with its voice command', () => {
    const row = CONTROLS.find(c => c.action === 'table')
    expect(row).toMatchObject({ label: 'Set table', voice: 'verity table N' })
  })
})

describe('Controls menu', () => {
  it('lists every row within the card width and keeps the selection on screen', () => {
    for (const item of CONTROLS) expect(getTextWidth(controlRow(item, true))).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    const last = formatControls(CONTROLS.length - 1).split('\n')
    expect(last).toHaveLength(CARD_MAX_LINES)
    expect(last.at(-2)).toMatch(/^> Close \(hold\)/)
    expect(last.at(-1)?.trim()).toBe(CONTROLS_FOOTER)
    for (const l of last) expect(getTextWidth(l)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    expect(formatControls(0).split('\n')[0]).toMatch(/^> Clip last 2 min \(swipe back\)/)
  })

  it('stops at the ends: only hold, verity back or Close closes it', () => {
    expect(moveSelection(0, 'up')).toBe(0)
    expect(moveSelection(CONTROLS.length - 1, 'down')).toBe(CONTROLS.length - 1)
    expect(moveSelection(1, 'down')).toBe(2)
  })
})

describe('corner hint', () => {
  it('sits bottom right on its own line and never overlaps the card text', () => {
    const queue = [makeTask({ id: 'a' }), makeTask({ id: 'b' })]
    const lines = formatCard(queue, { offline: false, hint: CONTROLS_HINT }).text.split('\n')
    expect(lines).toHaveLength(CARD_MAX_LINES)
    expect(lines.at(-1)).toMatch(/\+1 queued · fwd: controls$/)
    for (const l of lines) expect(getTextWidth(l)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    const empty = formatCard([], { offline: false, hint: CONTROLS_HINT }).text.split('\n')
    expect(empty.at(-1)?.trim()).toBe(CONTROLS_HINT)
  })
})
