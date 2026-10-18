import { describe, expect, it } from 'vitest'
import { getTextWidth } from '@evenrealities/pretext'
import type { Alert } from './contract'
import { CARD_MAX_LINES, CARD_TEXT_WIDTH } from './card'
import {
  EMPTY_EXCEPTIONS,
  alertText,
  applyAlert,
  dismissTop,
  formatElapsed,
  formatExceptions,
  visibleAlerts,
  type Exceptions,
} from './exceptions'

const T0 = 1_000_000
const alert = (over: Partial<Alert> & { id: string }): Alert => ({ type: 'alert', level: 'warn', text: over.id, ...over })
const apply = (msgs: Alert[], now = T0, from: Exceptions = EMPTY_EXCEPTIONS) =>
  msgs.reduce((s, m) => applyAlert(s, m, now), from)
const ids = (s: Exceptions, now = T0) => visibleAlerts(s, now).map(a => a.id)

describe('formatElapsed', () => {
  it('shows seconds in 10 s steps under two minutes, then minutes, then hours', () => {
    expect(formatElapsed(0)).toBe('0s')
    expect(formatElapsed(45)).toBe('40s')
    expect(formatElapsed(60)).toBe('60s')
    expect(formatElapsed(119)).toBe('110s')
    expect(formatElapsed(120)).toBe('2m')
    expect(formatElapsed(14 * 60 + 59)).toBe('14m')
    expect(formatElapsed(65 * 60)).toBe('1h05')
  })
})

describe('exceptions ordering', () => {
  it('puts urgent before warn before info', () => {
    const s = apply([alert({ id: 'i', level: 'info' }), alert({ id: 'w' }), alert({ id: 'u', level: 'urgent' })])
    expect(ids(s)).toEqual(['u', 'w', 'i'])
  })

  it('orders the same level by longest running, then by arrival', () => {
    const s = apply([
      alert({ id: 'a' }),
      alert({ id: 'b', sinceSec: 30 }),
      alert({ id: 'c', sinceSec: 300 }),
      alert({ id: 'd' }),
    ])
    expect(ids(s)).toEqual(['c', 'b', 'a', 'd'])
  })

  it('re-sending an id replaces it in place and keeps its arrival order', () => {
    const s = apply([alert({ id: 'a' }), alert({ id: 'b' }), alert({ id: 'a', text: 'new text' })])
    expect(ids(s)).toEqual(['a', 'b'])
    expect(s.open.find(a => a.id === 'a')?.text).toBe('new text')
  })

  it('drops a cleared alert', () => {
    const s = apply([alert({ id: 'a' }), alert({ id: 'b' }), alert({ id: 'a', cleared: true })])
    expect(ids(s)).toEqual(['b'])
  })
})

describe('dismissing', () => {
  it('tap dismisses the top alert only', () => {
    const s = apply([alert({ id: 'w' }), alert({ id: 'u', level: 'urgent' })])
    const r = dismissTop(s, T0)
    expect(r.dismissed?.id).toBe('u')
    expect(ids(r.state)).toEqual(['w'])
    expect(dismissTop(EMPTY_EXCEPTIONS, T0).dismissed).toBeNull()
  })

  it('a dismissed alert stays hidden on re-send, but returns if it escalates', () => {
    const s = dismissTop(apply([alert({ id: 'a' })]), T0).state
    expect(ids(apply([alert({ id: 'a', text: 'again' })], T0, s))).toEqual([])
    expect(ids(apply([alert({ id: 'a', level: 'urgent' })], T0, s))).toEqual(['a'])
  })

  it('clearing forgets the dismissal, so a later alert with the same id shows', () => {
    let s = dismissTop(apply([alert({ id: 'a' })]), T0).state
    s = apply([alert({ id: 'a', cleared: true }), alert({ id: 'a' })], T0, s)
    expect(ids(s)).toEqual(['a'])
  })
})

describe('formatExceptions', () => {
  it('is blank with no exceptions, and says OFFLINE when offline', () => {
    expect(formatExceptions(EMPTY_EXCEPTIONS, T0, { offline: false }).text).toBe('')
    expect(formatExceptions(EMPTY_EXCEPTIONS, T0, { offline: true }).text).toBe('OFFLINE')
  })

  it('ticks {elapsed} from the local clock without a new message', () => {
    const s = apply([alert({ id: 'a', level: 'urgent', text: 'T4 waiting {elapsed} on mains', sinceSec: 14 * 60 })])
    expect(formatExceptions(s, T0, { offline: false }).text).toBe('! T4 waiting 14m on mains')
    expect(formatExceptions(s, T0 + 60_000, { offline: false }).text).toBe('! T4 waiting 15m on mains')
  })

  it('renders the brief examples, most urgent first', () => {
    const s = apply([
      alert({ id: 'vip', level: 'info', text: 'VIP seated T7' }),
      alert({ id: 'ack', text: 'T12 task unacked {elapsed}', sinceSec: 60 }),
      alert({ id: 'late', level: 'urgent', text: 'T4 waiting {elapsed} on mains', sinceSec: 840 }),
    ])
    const view = formatExceptions(s, T0, { offline: false })
    expect(view.text.split('\n')).toEqual(['! T4 waiting 14m on mains', 'T12 task unacked 60s', 'VIP seated T7'])
    expect(view.brightness).toBe(4)
  })

  it('dims with the most urgent level shown', () => {
    const b = (level: Alert['level']) => formatExceptions(apply([alert({ id: 'a', level })]), T0, { offline: false }).brightness
    expect(b('urgent')).toBeGreaterThan(b('warn'))
    expect(b('warn')).toBeGreaterThan(b('info'))
    expect(b('info')).toBeGreaterThan(0)
  })

  it('caps at the line limit with +N more', () => {
    const s = apply(Array.from({ length: 8 }, (_, i) => alert({ id: `a${i}` })))
    const l = formatExceptions(s, T0, { offline: false }).text.split('\n')
    expect(l).toHaveLength(CARD_MAX_LINES)
    expect(l.at(-1)).toBe(`+${8 - (CARD_MAX_LINES - 1)} more`)
  })

  it('shares the footer line between OFFLINE and +N more', () => {
    const s = apply(Array.from({ length: 8 }, (_, i) => alert({ id: `a${i}` })))
    const l = formatExceptions(s, T0, { offline: true }).text.split('\n')
    expect(l).toHaveLength(CARD_MAX_LINES)
    expect(l.at(-1)!.startsWith('OFFLINE')).toBe(true)
    expect(l.at(-1)!.endsWith(`+${8 - (CARD_MAX_LINES - 1)} more`)).toBe(true)
  })

  it('fits every line to the card width', () => {
    const s = apply([alert({ id: 'a', text: 'W'.repeat(200) })])
    const line = formatExceptions(s, T0, { offline: false }).text
    expect(getTextWidth(line)).toBeLessThanOrEqual(CARD_TEXT_WIDTH)
    expect(alertText(s.open[0]!, T0)).toHaveLength(200)
  })
})
