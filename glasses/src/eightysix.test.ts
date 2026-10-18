import { describe, expect, it } from 'vitest'
import { getTextWidth } from '@evenrealities/pretext'
import { CARD_TEXT_WIDTH, formatCard } from './card'
import type { Alert } from './contract'
import { alertText, type OpenAlert } from './exceptions'
import { EightySix } from './eightysix'
import { makeTask } from './fixtures.test-helpers'

const out86 = (dish: string, cleared = false): Alert => ({
  type: 'alert',
  id: `86-${dish}`,
  level: 'warn',
  text: cleared ? '' : `86 ${dish}`,
  table: '',
  sinceSec: 0,
  kind: '86',
  ...(cleared ? { cleared: true } : {}),
})

describe('EightySix', () => {
  it('keeps one line of what is out and drops a dish on un-86', () => {
    const e = new EightySix()
    expect(e.line()).toBe('')
    expect(e.apply(out86('halibut'))).toBe(true)
    expect(e.line()).toBe('86 halibut')
    e.apply(out86('risotto'))
    e.apply(out86('halibut')) // the replay on reconnect is not a second dish
    expect(e.line()).toBe('86 halibut, risotto')
    e.apply(out86('halibut', true))
    expect(e.line()).toBe('86 risotto')
    e.apply(out86('risotto', true))
    expect(e.line()).toBe('')
  })

  it('ignores manager exceptions', () => {
    const e = new EightySix()
    const vip: Alert = { type: 'alert', id: 'vip-T7', level: 'info', text: 'VIP seated T7', kind: 'vip' }
    expect(e.apply(vip)).toBe(false)
    expect(e.line()).toBe('')
  })
})

describe('86 on the server card', () => {
  it('sits under the allergies, above the task', () => {
    const task = makeTask({ allergies: [{ allergen: 'shellfish', seats: [3] }] })
    const l = formatCard([task], { offline: false, eightySix: '86 halibut' }).text.split('\n')
    expect(l.slice(0, 3)).toEqual(['! SHELLFISH s3', '86 halibut', 'RUN · T12 · 2× halibut s1+3'])
  })

  it('shows alone, dim, when nothing needs the server', () => {
    expect(formatCard([], { offline: false, eightySix: '86 halibut' })).toEqual({ text: '86 halibut', brightness: 2 })
    expect(formatCard([], { offline: true, eightySix: '86 halibut' }).text).toBe('86 halibut\nOFFLINE')
  })
})

describe('new alert lines fit one G2 line (pretext)', () => {
  // worst case: two hours on mains ('2h00')
  const waited: OpenAlert = { id: 'course-T4', level: 'urgent', text: 'T4 waiting {elapsed} on mains', since: -7200_000, seq: 0 }
  const lines = [
    '86 halibut',
    '86 halibut, risotto, salmon, chocolate torte',
    'VIP seated T7',
    alertText(waited, 0),
  ]
  it.each(lines)('%s', text => {
    expect(getTextWidth(text)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
  })
})
