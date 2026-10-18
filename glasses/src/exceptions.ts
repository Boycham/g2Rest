import type { Alert, AlertLevel } from './contract'
import { CARD_MAX_LINES, CARD_TEXT_WIDTH, fit, spread, type CardView } from './card'

// The manager's exceptions view: the backend decides what is an exception (Coder A's
// rules); the glasses keep the open ones, tick their timers locally and order them.

export interface OpenAlert {
  id: string
  level: AlertLevel
  text: string
  table?: string
  /** Epoch ms when the condition started, or null when the alert has no timer. */
  since: number | null
  /** Arrival order, to keep ties stable. */
  seq: number
}

export interface Exceptions {
  open: readonly OpenAlert[]
  /** Locally dismissed ids, with the level they had when dismissed. */
  dismissed: Readonly<Record<string, AlertLevel>>
  nextSeq: number
}

export const EMPTY_EXCEPTIONS: Exceptions = { open: [], dismissed: {}, nextSeq: 0 }

const RANK: Record<AlertLevel, number> = { info: 0, warn: 1, urgent: 2 }
const BRIGHTNESS: Record<AlertLevel, number> = { info: 2, warn: 3, urgent: 4 }

export const ELAPSED_TOKEN = '{elapsed}'

function without<T>(rec: Readonly<Record<string, T>>, key: string): Record<string, T> {
  const next = { ...rec }
  delete next[key]
  return next
}

/** Add, replace or clear one alert. A dismissed alert comes back only if it escalates. */
export function applyAlert(state: Exceptions, msg: Alert, now: number): Exceptions {
  const rest = state.open.filter(a => a.id !== msg.id)
  if (msg.cleared) return { ...state, open: rest, dismissed: without(state.dismissed, msg.id) }
  const prev = state.open.find(a => a.id === msg.id)
  const alert: OpenAlert = {
    id: msg.id,
    level: msg.level,
    text: msg.text,
    ...(msg.table !== undefined ? { table: msg.table } : {}),
    since: msg.sinceSec !== undefined ? now - msg.sinceSec * 1000 : null,
    seq: prev ? prev.seq : state.nextSeq,
  }
  const was = state.dismissed[msg.id]
  const dismissed = was !== undefined && RANK[msg.level] > RANK[was] ? without(state.dismissed, msg.id) : state.dismissed
  return { open: [...rest, alert], dismissed, nextSeq: prev ? state.nextSeq : state.nextSeq + 1 }
}

export function elapsedSec(a: OpenAlert, now: number): number {
  return a.since === null ? 0 : Math.max(0, Math.floor((now - a.since) / 1000))
}

/** Most urgent first: level, then longest running, then oldest. Dismissed ones are hidden. */
export function visibleAlerts(state: Exceptions, now: number): OpenAlert[] {
  return state.open
    .filter(a => state.dismissed[a.id] === undefined)
    .sort((a, b) => RANK[b.level] - RANK[a.level] || elapsedSec(b, now) - elapsedSec(a, now) || a.seq - b.seq)
}

/** Tap: dismiss the top exception locally (the contract has no ack message yet). */
export function dismissTop(state: Exceptions, now: number): { state: Exceptions; dismissed: OpenAlert | null } {
  const top = visibleAlerts(state, now)[0]
  if (!top) return { state, dismissed: null }
  return { state: { ...state, dismissed: { ...state.dismissed, [top.id]: top.level } }, dismissed: top }
}

/**
 * "45s" under two minutes (in 10 s steps, so the line changes at most every 10 s),
 * then whole minutes ("14m"), then hours ("1h05").
 */
export function formatElapsed(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s < 120) return `${Math.floor(s / 10) * 10}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`
}

export function alertText(a: OpenAlert, now: number): string {
  const text = a.text.split(ELAPSED_TOKEN).join(formatElapsed(elapsedSec(a, now)))
  return a.level === 'urgent' ? `! ${text}` : text
}

export interface ExceptionsOptions {
  offline: boolean
  width?: number
  maxLines?: number
}

/** Blank when there is nothing to act on. Brightness follows the most urgent line. */
export function formatExceptions(state: Exceptions, now: number, opts: ExceptionsOptions): CardView {
  const width = opts.width ?? CARD_TEXT_WIDTH
  const maxLines = opts.maxLines ?? CARD_MAX_LINES
  const alerts = visibleAlerts(state, now)
  const footer = opts.offline ? 'OFFLINE' : ''
  if (!alerts.length) return { text: footer, brightness: 4 }

  const room = maxLines - (footer ? 1 : 0)
  const fits = alerts.length <= room
  // Without a footer, "+N more" needs its own line; with one, it shares the footer.
  const shown = fits ? alerts : alerts.slice(0, footer ? room : room - 1)
  const lines = shown.map(a => fit(alertText(a, now), width))
  const more = fits ? '' : `+${alerts.length - shown.length} more`
  if (more && !footer) lines.push(more)
  if (footer) lines.push(spread(footer, more, width))
  return { text: lines.join('\n'), brightness: BRIGHTNESS[alerts[0]!.level] }
}

/** Phone mirror: same order, no truncation. */
export function alertRows(state: Exceptions, now: number): string[] {
  return visibleAlerts(state, now).map(a => alertText(a, now))
}
