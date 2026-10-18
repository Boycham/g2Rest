import { getTextWidth } from '@evenrealities/pretext'
import menuJson from '../../data/menu.json'
import type { Allergy, Task, TaskItem } from './contract'
import { CARD_PADDING, CARD_TEXT_WIDTH, DISPLAY_HEIGHT, fit, seatsLabel, spread, type CardView } from './card'
import { LINE_PX } from './draft'
import { wrap } from './talk'

// New-server ramp mode: what is on each plate of the current card, its allergens and the wine
// to pour, one dish per page (tap = next, hold = back to the Card). Ramp-on staff also get a
// one-line dish hint on RUN cards. The menu is bundled from data/menu.json, so nothing here
// waits on the network or a model.

export interface RampDish {
  name: string
  aliases: readonly string[]
  allergens: readonly string[]
  components: readonly string[]
  pairing: string
}

const norm = (s: string) => s.toLowerCase().replace(/-/g, ' ').split(/\s+/).filter(Boolean).join(' ')

/** Dish lookup by name or alias, case/hyphen-insensitive, like the backend's Menu.find. */
export class RampMenu {
  private readonly lookup = new Map<string, RampDish>()

  constructor(dishes: readonly RampDish[]) {
    for (const d of dishes) for (const key of [d.name, ...d.aliases]) this.lookup.set(norm(key), d)
  }

  find(name: string): RampDish | undefined {
    const key = norm(name).replace(/^the /, '')
    return this.lookup.get(key) ?? this.lookup.get(key.replace(/s$/, ''))
  }
}

export const MENU = new RampMenu(menuJson.dishes)

/** Lines on a ramp page, footer included: the full-screen text height in 27 px lines, so the footer sits at the bottom. */
export const RAMP_MAX_LINES = Math.floor((DISPLAY_HEIGHT - 2 * CARD_PADDING) / LINE_PX)
export const RAMP_COMPONENT_LINES = 2
export const RAMP_NEXT = 'tap: next · hold: card'
export const RAMP_ONLY = 'hold: card'
export const NOT_IN_MENU = 'not in menu data'

export interface RampPage {
  item: TaskItem
  dish?: RampDish
}

/** One page per distinct dish on the task, in card order. */
export function rampPages(task: Task | undefined, menu: RampMenu = MENU): RampPage[] {
  if (!task) return []
  const seen = new Set<string>()
  const pages: RampPage[] = []
  for (const item of task.items) {
    const dish = menu.find(item.dish)
    const key = dish?.name ?? norm(item.dish)
    if (seen.has(key)) continue
    seen.add(key)
    pages.push(dish ? { item, dish } : { item })
  }
  return pages
}

/** `allergens: fish, dairy`; one a seat at the table is allergic to is upper-cased with the seats and the line starts with `!`. */
export function allergenLine(dish: RampDish, allergies: readonly Allergy[]): string {
  if (!dish.allergens.length) return 'allergens: none listed'
  let hit = false
  const parts = dish.allergens.map(a => {
    const seats = allergies.filter(x => x.allergen.toLowerCase() === a.toLowerCase()).flatMap(x => x.seats)
    const match = allergies.some(x => x.allergen.toLowerCase() === a.toLowerCase())
    if (!match) return a
    hit = true
    const s = seatsLabel(seats)
    return s ? `${a.toUpperCase()} ${s}` : a.toUpperCase()
  })
  return `${hit ? '! ' : ''}allergens: ${parts.join(', ')}`
}

/** Page `page` (wrapping) of the ramp view: dish and seats, components, allergens, wine, footer. */
export function formatRamp(task: Task, page: number, width = CARD_TEXT_WIDTH, menu: RampMenu = MENU): CardView {
  const pages = rampPages(task, menu)
  if (!pages.length) return { text: fit('No dishes to ramp', width), brightness: 4 }
  const p = ((page % pages.length) + pages.length) % pages.length
  const { item, dish } = pages[p]!
  const seats = seatsLabel(item.seats)
  const title = [dish?.name ?? item.dish, seats].filter(Boolean).join(' · ')
  const lines = [spread(title, `${p + 1}/${pages.length}`, width)]
  if (dish) {
    lines.push(...wrap(dish.components.join(', '), width, RAMP_COMPONENT_LINES))
    lines.push(fit(allergenLine(dish, task.allergies), width))
    lines.push(fit(`wine: ${dish.pairing}`, width))
  } else {
    lines.push(fit(`${item.dish}: ${NOT_IN_MENU}`, width))
  }
  const pad = Array<string>(Math.max(0, RAMP_MAX_LINES - 1 - lines.length)).fill('')
  const footer = spread('', pages.length > 1 ? RAMP_NEXT : RAMP_ONLY, width)
  return { text: [...lines, ...pad, footer].join('\n'), brightness: 4 }
}

/** The RUN-card hint for ramp-on staff: `ramp · halibut: brown butter, capers · salmon: …`, measured to one line. */
export function rampHint(task: Task | undefined, width: number, menu: RampMenu = MENU): string {
  if (task?.kind !== 'RUN') return ''
  const known = rampPages(task, menu).filter(p => p.dish)
  if (!known.length) return ''
  // Components that only repeat the dish's own name ("halibut" on halibut) say nothing new.
  const extras = (p: RampPage) => p.dish!.components.filter(c => !norm(c).includes(norm(p.item.dish)))
  const line = (n: number) => `ramp · ${known.map(p => `${p.item.dish}: ${extras(p).slice(0, n).join(', ')}`).join(' · ')}`
  const two = line(2)
  return fit(getTextWidth(two) <= width ? two : line(1), width)
}

/** Ramp hints on or off per staff id (SDK storage `fs.ramp.v1`). Off unless turned on. */
export type RampPrefs = Readonly<Record<string, boolean>>

export function parseRampPrefs(raw: string): RampPrefs | null {
  try {
    const v: unknown = JSON.parse(raw)
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return null
    const entries = Object.entries(v)
    return entries.every(([, on]) => typeof on === 'boolean') ? Object.fromEntries(entries) : null
  } catch {
    return null
  }
}

export const rampOn = (prefs: RampPrefs, staff: string): boolean => prefs[staff] === true

export const withRamp = (prefs: RampPrefs, staff: string, on: boolean): RampPrefs => ({ ...prefs, [staff]: on })
