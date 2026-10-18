import { getAdvW, getTextWidth } from '@evenrealities/pretext'
import { describe, expect, it } from 'vitest'
import menuJson from '../../data/menu.json'
import { CARD_MAX_LINES, CARD_TEXT_WIDTH, TAB_TEXT_WIDTH, formatCard } from './card'
import { CONTROLS } from './controls'
import { makeTask } from './fixtures.test-helpers'
import {
  MENU,
  NOT_IN_MENU,
  RAMP_MAX_LINES,
  RAMP_NEXT,
  RAMP_ONLY,
  allergenLine,
  formatRamp,
  parseRampPrefs,
  rampHint,
  rampOn,
  rampPages,
  withRamp,
} from './ramp'

const run = makeTask({
  items: [
    { qty: 2, dish: 'halibut', seats: [1, 3] },
    { qty: 1, dish: 'salmon', seats: [2] },
  ],
  allergies: [{ allergen: 'FISH', seats: [2] }],
})

describe('menu data', () => {
  it('gives every dish components and a pairing, in glyphs the G2 font has', () => {
    for (const d of menuJson.dishes) {
      expect(d.components.length, d.name).toBeGreaterThan(0)
      expect(d.pairing, d.name).not.toBe('')
      for (const ch of [...d.components.join(''), ...d.pairing]) expect(getAdvW(ch.codePointAt(0)!), ch).toBeGreaterThan(0)
    }
  })

  it('finds a dish by name or alias like the backend does', () => {
    expect(MENU.find('halibut')?.name).toBe('Pan-Roasted Halibut')
    expect(MENU.find('pan roasted halibut')?.name).toBe('Pan-Roasted Halibut')
    expect(MENU.find('the scallops')?.name).toBe('Scallop Crudo')
    expect(MENU.find('short rib')).toBeUndefined()
  })
})

describe('ramp view', () => {
  it('has one page per distinct dish, tap wraps around', () => {
    expect(rampPages(run).map(p => p.dish?.name)).toEqual(['Pan-Roasted Halibut', 'Cedar Plank Salmon'])
    expect(rampPages(makeTask({ items: [] }))).toEqual([])
    expect(formatRamp(run, 2).text).toBe(formatRamp(run, 0).text)
  })

  it('shows dish and seats, components, allergens, wine, then the footer', () => {
    const l = formatRamp(run, 0).text.split('\n')
    expect(l[0]).toMatch(/^Pan-Roasted Halibut · s1\+3 +1\/2$/)
    expect(l[1]).toBe('halibut, brown butter, capers, leeks, fingerling potatoes')
    expect(l[2]).toBe('! allergens: FISH s2, dairy')
    expect(l[3]).toBe('wine: Sancerre, Loire')
    expect(l.at(-1)?.trimStart()).toBe(RAMP_NEXT)
    expect(formatRamp(run, 1).text.split('\n')[2]).toBe('! allergens: FISH s2')
  })

  it('fits every dish of the menu on one page within the full-screen width', () => {
    for (const d of menuJson.dishes) {
      const task = makeTask({ items: [{ qty: 1, dish: d.name, seats: [1] }] })
      const l = formatRamp(task, 0).text.split('\n')
      expect(l, d.name).toHaveLength(RAMP_MAX_LINES)
      expect(l.at(-1)?.trimStart()).toBe(RAMP_ONLY)
      for (const line of l) expect(getTextWidth(line), line).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    }
  })

  it('says when a dish is not in the menu data', () => {
    const l = formatRamp(makeTask({ items: [{ qty: 1, dish: 'short rib', seats: [4] }] }), 0).text.split('\n')
    expect(l[0]).toMatch(/^short rib · s4/)
    expect(l[1]).toBe(`short rib: ${NOT_IN_MENU}`)
  })

  it('marks no allergens plainly', () => {
    expect(allergenLine(MENU.find('duck')!, [])).toBe('allergens: none listed')
    expect(allergenLine(MENU.find('scallops')!, [{ allergen: 'SHELLFISH', seats: [3] }])).toBe('! allergens: SHELLFISH s3, citrus')
  })
})

describe('ramp hint on RUN cards', () => {
  it('is one measured line, RUN only', () => {
    const hint = rampHint(run, TAB_TEXT_WIDTH)
    expect(hint).toBe('ramp · halibut: brown butter · salmon: cedar smoke')
    expect(rampHint(makeTask(), TAB_TEXT_WIDTH)).toBe('ramp · halibut: brown butter, capers')
    expect(getTextWidth(hint)).toBeLessThanOrEqual(TAB_TEXT_WIDTH)
    expect(rampHint(makeTask({ kind: 'CHECK', items: [] }), TAB_TEXT_WIDTH)).toBe('')
    expect(rampHint(makeTask({ kind: 'ORDER' }), TAB_TEXT_WIDTH)).toBe('')
    expect(rampHint(makeTask({ items: [{ qty: 1, dish: 'short rib', seats: [] }] }), TAB_TEXT_WIDTH)).toBe('')
  })

  it('sits under the task line and keeps the card at 5 lines with the footer', () => {
    const queue = [{ ...run, notes: ['VIP: anniversary'] }, makeTask({ id: 'b' })]
    const lines = formatCard(queue, {
      offline: false,
      hint: 'fwd: queue',
      width: TAB_TEXT_WIDTH,
      detail: rampHint(run, TAB_TEXT_WIDTH),
    }).text.split('\n')
    expect(lines).toHaveLength(CARD_MAX_LINES)
    expect(lines[0]).toBe('! FISH s2')
    expect(lines[1]).toMatch(/^RUN · T12/)
    expect(lines[2]).toMatch(/^ramp · /)
    expect(lines[3]).toBe('VIP: anniversary')
    for (const l of lines) expect(getTextWidth(l)).toBeLessThanOrEqual(TAB_TEXT_WIDTH)
  })
})

describe('ramp settings', () => {
  it('are per staff member and off by default', () => {
    const prefs = withRamp({}, 's1', true)
    expect(rampOn(prefs, 's1')).toBe(true)
    expect(rampOn(prefs, 's2')).toBe(false)
    expect(rampOn(withRamp(prefs, 's1', false), 's1')).toBe(false)
    expect(parseRampPrefs(JSON.stringify(prefs))).toEqual({ s1: true })
    expect(parseRampPrefs('{"s1": "yes"}')).toBeNull()
    expect(parseRampPrefs('[]')).toBeNull()
    expect(parseRampPrefs('nope')).toBeNull()
  })

  it('are listed in Controls', () => {
    expect(CONTROLS.find(c => c.label === 'Ramp')?.voice).toBe('verity ramp')
    expect(CONTROLS.find(c => c.label === 'Ramp hints')?.voice).toBe('verity ramp on/off')
  })
})
