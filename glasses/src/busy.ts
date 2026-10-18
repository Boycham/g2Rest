// "Verity is thinking": a short label whose dots cycle . -> .. -> ... while a clip or an
// unknown "verity" phrase is being worked on. One tick rewrites one text container in place.

/** 2.5 updates a second: visibly alive, and far from one BLE write per frame. */
export const BUSY_TICK_MS = 400
export const PROCESSING = 'Verity: processing'
export const SUMMARY = 'summary'

export function dots(label: string, tick: number): string {
  return label + '.'.repeat((tick % 3) + 1)
}

/** A setInterval that only runs while something is busy; `tick` counts its beats. */
export class Ticker {
  private timer: ReturnType<typeof setInterval> | null = null
  tick = 0

  constructor(
    private readonly onTick: () => void,
    private readonly ms = BUSY_TICK_MS,
  ) {}

  get running(): boolean {
    return this.timer !== null
  }

  /** Start or stop to match `on`; starting again keeps the beat it is on. */
  set(on: boolean): void {
    if (on && !this.timer) {
      this.tick = 0
      this.timer = setInterval(() => {
        this.tick++
        this.onTick()
      }, this.ms)
    } else if (!on && this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  }
}
