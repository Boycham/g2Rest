import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUSY_TICK_MS, PROCESSING, Ticker, dots } from './busy'

describe('dots', () => {
  it('cycles one, two, three dots', () => {
    expect([0, 1, 2, 3].map(t => dots(PROCESSING, t))).toEqual([
      'Verity: processing.',
      'Verity: processing..',
      'Verity: processing...',
      'Verity: processing.',
    ])
  })
})

describe('Ticker', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('beats at about 2.5 a second only while on', () => {
    const onTick = vi.fn()
    const t = new Ticker(onTick)
    t.set(true)
    t.set(true)
    vi.advanceTimersByTime(1000)
    expect(onTick).toHaveBeenCalledTimes(Math.floor(1000 / BUSY_TICK_MS))
    expect(t.tick).toBe(2)
    t.set(false)
    expect(t.running).toBe(false)
    vi.advanceTimersByTime(5000)
    expect(onTick).toHaveBeenCalledTimes(2)
  })
})
