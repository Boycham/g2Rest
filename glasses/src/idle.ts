// Quiet by design: with no task, no queue and nothing open, the server HUD goes fully blank.
// It wakes on a tap, a new task, an alert or a screen-needing voice command, and blanks again
// after IDLE_MS without input (DONE_BEAT_MS right after the last task is done).

/** How long a woken, idle HUD stays on without input before it blanks. */
export const IDLE_MS = 8000
/** After the last task is done: long enough to see `Done`, then blank. */
export const DONE_BEAT_MS = 1500

/**
 * The blank/wake state machine. `held` is "something needs the screen" (a task, the draft, a
 * popup, the processing indicator, the ramp view); while held the HUD stays awake and no timer
 * runs. When nothing holds it, it blanks after the delay of the last wake (default IDLE_MS).
 * `onChange(awake)` fires on every transition, never twice for the same state.
 */
export class IdleBlank {
  private on = true
  private held = false
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(private readonly onChange: (awake: boolean) => void) {}

  get awake(): boolean {
    return this.on
  }

  /** Call after every state change: a hold wakes and stops the timer; a release starts it. */
  update(held: boolean): void {
    this.held = held
    if (held) {
      this.stopTimer()
      this.set(true)
    } else if (this.on && !this.timer) this.startTimer(IDLE_MS)
  }

  /** Wake (tap, alert, "verity menu"...) and blank `ms` after this unless held or poked again. */
  wake(ms = IDLE_MS): void {
    this.set(true)
    this.stopTimer()
    if (!this.held) this.startTimer(ms)
  }

  /** Input while awake and idle: restart the IDLE_MS countdown. */
  touch(): void {
    if (this.on && !this.held) this.wake(IDLE_MS)
  }

  /** Role off or exit: no timer left behind; awake again for the next enter(). */
  reset(): void {
    this.stopTimer()
    this.held = false
    this.on = true
  }

  private startTimer(ms: number): void {
    this.timer = setTimeout(() => {
      this.timer = null
      if (!this.held) this.set(false)
    }, ms)
  }

  private stopTimer(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
  }

  private set(awake: boolean): void {
    if (awake === this.on) return
    this.on = awake
    this.onChange(awake)
  }
}
