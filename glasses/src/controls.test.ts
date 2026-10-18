import { getTextWidth } from '@evenrealities/pretext'
import { describe, expect, it } from 'vitest'
import { CARD_MAX_LINES, TAB_RAIL_WIDTH, TAB_TEXT_WIDTH, CARD_PADDING, formatCard } from './card'
import {
  CARD_GESTURES,
  CARD_HINT,
  CONTROLS,
  CONTROLS_FOOTER,
  CONTROLS_PAGES,
  TABS,
  TAB_LABELS,
  controlRow,
  formatControls,
  nextControlsPage,
  tabAfter,
} from './controls'
import { makeTask } from './fixtures.test-helpers'

describe('tabs', () => {
  it('stacks Controls, Queue, Task top to bottom; swipe fwd goes up, swipe back down', () => {
    expect(TABS).toEqual(['controls', 'queue', 'card'])
    expect(tabAfter('card', 'up')).toBe('queue')
    expect(tabAfter('queue', 'up')).toBe('controls')
    expect(tabAfter('controls', 'up')).toBeNull()
    expect(tabAfter('controls', 'down')).toBe('queue')
    expect(tabAfter('queue', 'down')).toBe('card')
    expect(tabAfter('card', 'down')).toBeNull()
  })

  it('fits every tab label in the rail', () => {
    for (const t of TABS) expect(getTextWidth(TAB_LABELS[t])).toBeLessThanOrEqual(TAB_RAIL_WIDTH - 2 * CARD_PADDING - 2)
  })

  it('lists Set table with its voice command', () => {
    const row = CONTROLS.find(c => c.label === 'Set table')
    expect(row).toMatchObject({ label: 'Set table', voice: 'verity table N' })
  })
})

describe('Task tab gestures', () => {
  it('keeps clip on swipe back (SDK down), the bottom tab', () => {
    expect(CARD_GESTURES).toEqual({ tap: 'task', up: 'queue', down: 'clip', hold: 'handoff' })
  })
})

describe('Controls tab', () => {
  it('is a reference list without Queue, every row within the tab width', () => {
    expect(CONTROLS.map(c => c.label)).not.toContain('Queue')
    for (const item of CONTROLS) expect(getTextWidth(controlRow(item))).toBeLessThanOrEqual(TAB_TEXT_WIDTH)
    expect(CONTROLS.find(c => c.label === 'Decline')?.voice).toBe('verity decline')
    expect(CONTROLS.find(c => c.label === 'Revert last')?.voice).toBe('verity revert')
  })

  it('pages by tap and wraps, the footer on the last line', () => {
    expect(CONTROLS_PAGES).toBe(3)
    expect(nextControlsPage(0)).toBe(1)
    expect(nextControlsPage(CONTROLS_PAGES - 1)).toBe(0)
    for (let p = 0; p < CONTROLS_PAGES; p++) {
      const l = formatControls(p).split('\n')
      expect(l).toHaveLength(CARD_MAX_LINES)
      expect(l.at(-1)).toMatch(new RegExp(`^${p + 1}/${CONTROLS_PAGES} .*${CONTROLS_FOOTER}$`))
      for (const line of l) expect(getTextWidth(line)).toBeLessThanOrEqual(TAB_TEXT_WIDTH)
    }
    expect(formatControls(0).split('\n')[0]).toMatch(/^Accept \/ done \(tap\)/)
    expect(formatControls(0)).not.toMatch(/^>/m)
  })
})

describe('Task tab corner hint', () => {
  it('sits bottom right on its own line and never overlaps the card text', () => {
    const queue = [makeTask({ id: 'a' }), makeTask({ id: 'b' })]
    const lines = formatCard(queue, { offline: false, hint: CARD_HINT, width: TAB_TEXT_WIDTH }).text.split('\n')
    expect(lines).toHaveLength(CARD_MAX_LINES)
    expect(lines.at(-1)).toMatch(/\+1 queued · fwd: queue$/)
    for (const l of lines) expect(getTextWidth(l)).toBeLessThanOrEqual(TAB_TEXT_WIDTH)
    const empty = formatCard([], { offline: false, hint: CARD_HINT, width: TAB_TEXT_WIDTH }).text.split('\n')
    expect(empty.at(-1)?.trim()).toBe(CARD_HINT)
  })
})
