import { describe, expect, it } from 'vitest'
import { NOD_DEFAULTS, NodDetector, nodWanted, parseNodConfig, syntheticNod, type NodConfig, type SyntheticNod } from './nod'

function nods(samples: { t: number; sample: object }[], cfg: NodConfig = NOD_DEFAULTS): number[] {
  const d = new NodDetector(cfg)
  return samples.filter(s => d.push(s.sample, s.t)).map(s => s.t)
}

const nod = (over: Partial<SyntheticNod> = {}, cfg?: NodConfig) =>
  syntheticNod({ restMs: 1000, depth: 0.5, durationMs: 400, hz: 20, base: -0.9, jitter: 0.04, ...over }, cfg)

describe('NodDetector on synthetic samples (20 Hz)', () => {
  it('fires once on a deliberate down-up nod, as the head comes back up', () => {
    const at = nods(nod())
    expect(at).toHaveLength(1)
    expect(at[0]).toBeGreaterThan(1200)
    expect(at[0]).toBeLessThanOrEqual(1400)
  })

  it('ignores a small head bob, walking jitter and a slow posture change', () => {
    expect(nods(nod({ depth: 0.15 }))).toEqual([])
    expect(nods(nod({ depth: 0, jitter: 0.3 }))).toEqual([])
    const drift = Array.from({ length: 100 }, (_, i) => ({ t: i * 50, sample: { y: -0.9 - i * 0.006 } }))
    expect(nods(drift)).toEqual([])
  })

  it('ignores looking down and staying down (reading the plate)', () => {
    expect(nods(nod({ durationMs: 2500 }))).toEqual([])
  })

  it('ignores a dip faster than minMs (a bump, not a nod)', () => {
    expect(nods(nod({ durationMs: 100 }))).toEqual([])
  })

  it('never fires when the IMU turns on with the head already down', () => {
    const fromBottom = nod().filter(s => s.t >= 1200).map(s => ({ t: s.t - 1200, sample: s.sample }))
    expect(nods(fromBottom)).toEqual([])
  })

  it('takes one nod per refractory window', () => {
    const first = nod({ afterMs: 300 })
    const t0 = first.at(-1)!.t + 50
    const again = (gap: number) =>
      nod({ restMs: gap, afterMs: 500 }).map(s => ({ t: s.t + t0, sample: s.sample }))
    expect(nods([...first, ...again(200)])).toHaveLength(1)
    expect(nods([...first, ...again(1600)])).toHaveLength(2)
  })

  it('works on another axis and sign, as configured', () => {
    const cfg = { ...NOD_DEFAULTS, axis: 'x' as const, sign: -1 as const }
    expect(nods(nod({}, cfg), cfg)).toHaveLength(1)
    expect(nods(nod({}, cfg))).toEqual([])
  })

  it('in rate mode (upLevel +1) needs the opposite swing, not just the stop', () => {
    const cfg = { ...NOD_DEFAULTS, upLevel: 1, base: 0 }
    const lobe = (t: number, a: number) => (t >= 1000 && t < 1200 ? -a : t >= 1200 && t < 1400 ? a : 0)
    const rate = (a: number) => Array.from({ length: 60 }, (_, i) => ({ t: i * 50, sample: { y: lobe(i * 50, 0.4 * a) } }))
    expect(nods(rate(1), cfg)).toHaveLength(1)
    const downOnly = Array.from({ length: 60 }, (_, i) => ({ t: i * 50, sample: { y: i * 50 >= 1000 && i * 50 < 1200 ? -0.4 : 0 } }))
    expect(nods(downOnly, cfg)).toEqual([])
  })

  it('skips samples without the axis or with junk values', () => {
    const d = new NodDetector()
    expect(d.push({}, 0)).toBe(false)
    expect(d.push({ y: Number.NaN }, 50)).toBe(false)
    expect(nods([{ t: 0, sample: { x: 1 } }, ...nod()])).toHaveLength(1)
  })
})

describe('nod config and gating', () => {
  it('reads VITE_FS_NOD over the defaults; off turns it off', () => {
    expect(parseNodConfig(undefined)).toEqual(NOD_DEFAULTS)
    expect(parseNodConfig('off')).toBeNull()
    expect(parseNodConfig('axis=x, sign=-1, threshold=0.4, maxMs=800')).toEqual({
      ...NOD_DEFAULTS,
      axis: 'x',
      sign: -1,
      threshold: 0.4,
      maxMs: 800,
    })
    expect(parseNodConfig('axis=w,threshold=abc,bogus=1')).toEqual(NOD_DEFAULTS)
    expect(parseNodConfig('threshold=-1')).toEqual(NOD_DEFAULTS)
  })

  it('is only wanted while a task waits to be accepted, off the draft and the handoff popup', () => {
    expect(nodWanted({ state: 'assigned' }, 'card', false)).toBe(true)
    expect(nodWanted({ state: 'assigned' }, 'ramp', false)).toBe(true)
    expect(nodWanted({ state: 'accepted' }, 'card', false)).toBe(false)
    expect(nodWanted(undefined, 'card', false)).toBe(false)
    expect(nodWanted({ state: 'assigned' }, 'draft', false)).toBe(false)
    expect(nodWanted({ state: 'assigned' }, 'card', true)).toBe(false)
  })
})
