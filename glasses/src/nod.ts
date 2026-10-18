// Head-nod to accept: with plates in both hands, a deliberate down-up nod sends the same
// task.accept as a tap. SDK 0.0.16 has `imuControl(on, pace)` and IMU_DATA_REPORT (8) sys events
// carrying `imuData {x, y, z}` (raw doubles; the SDK and docs give no units or axis frame, and
// the simulator always sends null). So this works on one configurable axis, relative to a slow
// baseline, and every number here is HW-PENDING until tuned on a real G2. Only on while a task
// waits to be accepted.

export interface ImuSample {
  x?: number
  y?: number
  z?: number
}

export interface NodConfig {
  axis: 'x' | 'y' | 'z'
  /** +1 if a head-down nod makes the axis value fall, -1 if it rises. */
  sign: 1 | -1
  /** How far below the baseline counts as "down", in the sensor's units. */
  threshold: number
  /**
   * Where "back up" is, as a multiple of the threshold relative to the baseline: -0.5 = back
   * within half the dip (an angle or gravity signal); +1 = an opposite swing as deep as the dip
   * (an angular-rate signal, whose down-up nod is a negative then a positive lobe).
   */
  upLevel: number
  /** A nod's down-to-up time must be within [minMs, maxMs]; held down longer = looking down, not a nod. */
  minMs: number
  maxMs: number
  /** Baseline time constant: slow posture changes are followed, a nod is not. */
  baselineMs: number
  /** Samples before the baseline is trusted after the IMU turns on. */
  warmup: number
  /** No second nod for this long after one. */
  refractoryMs: number
}

export const NOD_DEFAULTS: NodConfig = {
  axis: 'y',
  sign: 1,
  threshold: 0.25,
  upLevel: -0.5,
  minMs: 150,
  maxMs: 900,
  baselineMs: 1500,
  warmup: 5,
  refractoryMs: 1500,
}

const NUMERIC = ['threshold', 'upLevel', 'minMs', 'maxMs', 'baselineMs', 'warmup', 'refractoryMs'] as const

/**
 * `VITE_FS_NOD`: empty = defaults, `off` = no nod, else `key=value` pairs over the defaults, e.g.
 * `axis=x,sign=-1,threshold=0.3,maxMs=800`. A bad value keeps the default for that key.
 */
export function parseNodConfig(raw: string | undefined): NodConfig | null {
  const text = (raw ?? '').trim()
  if (text.toLowerCase() === 'off') return null
  const cfg: NodConfig = { ...NOD_DEFAULTS }
  for (const pair of text.split(',')) {
    const [k, v] = pair.split('=').map(s => s.trim())
    if (!k || v === undefined) continue
    if (k === 'axis' && (v === 'x' || v === 'y' || v === 'z')) cfg.axis = v
    else if (k === 'sign' && (v === '1' || v === '-1')) cfg.sign = v === '1' ? 1 : -1
    else if ((NUMERIC as readonly string[]).includes(k) && Number.isFinite(Number(v)) && v !== '')
      cfg[k as (typeof NUMERIC)[number]] = Number(v)
  }
  return cfg.threshold > 0 && cfg.minMs < cfg.maxMs ? cfg : { ...NOD_DEFAULTS }
}

/** Down below the baseline by the threshold, then back up to `upLevel` within the time window. */
export class NodDetector {
  private baseline: number | null = null
  private lastT = 0
  private samples = 0
  private downAt: number | null = null
  private quietUntil = -Infinity

  constructor(readonly cfg: NodConfig = NOD_DEFAULTS) {}

  /** Forget the baseline (the IMU was just turned on, or a new task is waiting). */
  reset(): void {
    this.baseline = null
    this.samples = 0
    this.downAt = null
  }

  /** One IMU sample at time `t` (ms); true exactly when a nod completes. */
  push(sample: ImuSample, t: number): boolean {
    const raw = sample[this.cfg.axis]
    if (typeof raw !== 'number' || !Number.isFinite(raw)) return false
    const v = this.cfg.sign * raw
    this.samples++
    if (this.baseline === null) {
      this.baseline = v
      this.lastT = t
      return false
    }
    const dt = Math.max(0, t - this.lastT)
    this.lastT = t
    const d = v - this.baseline
    if (this.downAt === null) {
      if (this.samples > this.cfg.warmup && t >= this.quietUntil && d <= -this.cfg.threshold) {
        this.downAt = t
        return false
      }
      this.baseline += (1 - Math.exp(-dt / this.cfg.baselineMs)) * d
      return false
    }
    const held = t - this.downAt
    if (held > this.cfg.maxMs) {
      // Head stayed down (reading the plate, bending over the table): re-baseline, no nod.
      this.downAt = null
      this.baseline = v
      return false
    }
    if (d < this.cfg.upLevel * this.cfg.threshold) return false
    this.downAt = null
    if (held < this.cfg.minMs) return false
    this.quietUntil = t + this.cfg.refractoryMs
    return true
  }
}

/** A task waits to be accepted and nothing else would take the nod (draft, handoff popup). */
export function nodWanted(head: { state: string } | undefined, screen: string, popup: boolean): boolean {
  return head?.state === 'assigned' && screen !== 'draft' && !popup
}

export interface SyntheticNod {
  /** When the nod starts, after `restMs` of still head. */
  restMs: number
  /** Dip depth in sensor units (a deliberate nod is well past the threshold). */
  depth: number
  /** Down-to-up duration of the nod. */
  durationMs: number
  hz: number
  base?: number
  /** Peak-to-peak jitter added to every sample (deterministic). */
  jitter?: number
  /** After the nod, keep the head still this long. */
  afterMs?: number
}

/** Samples of a still head, one half-sine dip on `cfg.axis`, then still again; for tests and `?debugImu=nod`. */
export function syntheticNod(n: SyntheticNod, cfg: NodConfig = NOD_DEFAULTS): { t: number; sample: ImuSample }[] {
  const out: { t: number; sample: ImuSample }[] = []
  const step = 1000 / n.hz
  const end = n.restMs + n.durationMs + (n.afterMs ?? 500)
  const base = n.base ?? 0
  for (let i = 0, t = 0; t <= end; i++, t = i * step) {
    const inNod = t >= n.restMs && t <= n.restMs + n.durationMs
    const dip = inNod ? n.depth * Math.sin((Math.PI * (t - n.restMs)) / n.durationMs) : 0
    const jitter = n.jitter ? (n.jitter / 2) * Math.sin(i * 2.399) : 0
    const v = cfg.sign * (base - dip + jitter)
    out.push({ t, sample: { x: 0, y: 0, z: 0, [cfg.axis]: v } })
  }
  return out
}
