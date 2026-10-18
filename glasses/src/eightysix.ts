import type { Alert } from './contract'

/**
 * What is 86'd tonight, on a server's glasses: the open `kind: '86'` alerts (backend pushes one
 * per dish, and replays them on connect). Shown as one line on the card until un-86'd.
 */
export class EightySix {
  private readonly dishes = new Map<string, string>()

  /** Takes an 86 alert or its clear; false for any other alert (manager exceptions). */
  apply(alert: Alert): boolean {
    if (alert.kind !== '86') return false
    if (alert.cleared) this.dishes.delete(alert.id)
    else this.dishes.set(alert.id, alert.text.replace(/^86\s+/, ''))
    return true
  }

  /** `86 halibut`, or `86 halibut, risotto` for more; '' when nothing is out. */
  line(): string {
    return this.dishes.size ? `86 ${[...this.dishes.values()].join(', ')}` : ''
  }
}
