import type * as SentryNs from './sentry-sdk'
import type { EvenAppBridge } from '@evenrealities/even_hub_sdk'
import type { BackendMessage, GlassesJsonMessage, TaskAssigned, TraceContext } from './contract'
import { version as APP_VERSION } from '../app.json'
import { dependencies } from '../package.json'
import { log } from './log'

// Sentry for the glasses WebView: errors, breadcrumbs, two spans (clip -> order card, task.assigned
// -> card) and a few Logs. Off unless the backend's GET /config returns a DSN, so none is packed
// into the .ehpk; the SDK itself is a lazy chunk only loaded then. Every hook here is a no-op while
// Sentry is off. Never sent: audio, transcripts or voice words, order or card text, the FS token.

type Sentry = typeof SentryNs
type Span = SentryNs.Span
type Data = Record<string, string | number | boolean>

export interface SentryConfig {
  dsn: string
  environment: string
  tracesSampleRate: number
}

const CONFIG_TIMEOUT_MS = 3000
/** No order card for a clip within this time ends its span as failed (the capture timeout is 30 s). */
const CLIP_SPAN_MAX_MS = 40_000
/** After the order card, how long the clip span waits for the summary before it ends. */
const SUMMARY_GRACE_MS = 8000
/** A task.assigned that redraws nothing within this time ends its span with `shown: false`. */
const CARD_SPAN_MAX_MS = 2000
/** A clip within this time of an input counts as started by it (`trigger`). */
const TRIGGER_MS = 2000

export const APP_TAGS = {
  app_version: APP_VERSION,
  even_hub_sdk: dependencies['@evenrealities/even_hub_sdk'],
} as const

// ---------- pure helpers (tested) ----------

const TOKEN_PARAM = /([?&]token=)[^&#\s"'\\]*/gi

export function scrubString(s: string, token: string): string {
  let out = s.replace(TOKEN_PARAM, '$1[Filtered]')
  if (token.length >= 4) out = out.split(token).join('[Filtered]')
  return out
}

/** Deep copy with the `token` query param (and the token itself) filtered out of every string. */
export function scrub<T>(value: T, token: string, depth = 0): T {
  if (typeof value === 'string') return scrubString(value, token) as T
  if (depth > 12 || value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(v => scrub(v, token, depth + 1)) as T
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(value)) out[k] = scrub(v, token, depth + 1)
  return out as T
}

/** `ws://host:8787/ws?token=…` -> `http://host:8787/config` (the token goes in a header instead). */
export function configUrl(wsUrl: string): string {
  const u = new URL(wsUrl)
  u.protocol = u.protocol === 'wss:' ? 'https:' : 'http:'
  u.pathname = '/config'
  u.search = ''
  u.hash = ''
  return u.toString()
}

/** The `sentry` part of GET /config: null when off or malformed. */
export function parseConfig(v: unknown): SentryConfig | null {
  if (!v || typeof v !== 'object') return null
  const o = v as Record<string, unknown>
  if (typeof o.dsn !== 'string' || !o.dsn.startsWith('https://')) return null
  const rate = typeof o.tracesSampleRate === 'number' && o.tracesSampleRate >= 0 && o.tracesSampleRate <= 1 ? o.tracesSampleRate : 1
  return { dsn: o.dsn, environment: typeof o.environment === 'string' ? o.environment : 'dev', tracesSampleRate: rate }
}

const SENTRY_TRACE = /^[0-9a-f]{32}-[0-9a-f]{16}(-[01])?$/

/** CONTRACT.md 8.12 `trace` on task.assigned, if well formed. */
export function traceOf(msg: { trace?: unknown }): TraceContext | null {
  const t = msg.trace as Partial<TraceContext> | undefined
  if (!t || typeof t.sentryTrace !== 'string' || !SENTRY_TRACE.test(t.sentryTrace)) return null
  return typeof t.baggage === 'string' ? { sentryTrace: t.sentryTrace, baggage: t.baggage } : { sentryTrace: t.sentryTrace }
}

/** What a frame may say in a breadcrumb: type, ids, kind, state, table. Never items, notes, words or text. */
export function frameData(msg: BackendMessage | GlassesJsonMessage): Data {
  const m = msg as unknown as Record<string, unknown>
  const out: Data = { type: msg.type }
  for (const k of ['taskId', 'captureId', 'mode', 'orderId', 'status', 'action', 'intent', 'voice', 'level'])
    if (typeof m[k] === 'string') out[k] = m[k] as string
  const task = m.task as Record<string, unknown> | undefined
  if (task) for (const k of ['id', 'kind', 'state', 'table']) if (typeof task[k] === 'string') out[`task.${k}`] = task[k] as string
  if (typeof m.table === 'string') out.table = m.table
  return out
}

// ---------- runtime ----------

let S: Sentry | null = null
let token = ''
let tags: Record<string, string> = { ...APP_TAGS }
const early: { category: string; message: string; data?: Data }[] = []
let lastInput: { how: string; at: number } | null = null

interface ClipSpan {
  id: string
  root: Span
  start: number
  trigger: string
  orderAt: number | null
  timer: ReturnType<typeof setTimeout>
}
let clip: ClipSpan | null = null

interface CardSpan {
  span: Span
  start: number
  timer: ReturnType<typeof setTimeout>
}
let cards: CardSpan[] = []

const debug = () => typeof location !== 'undefined' && new URLSearchParams(location.search).has('sentryDebug')

export interface StartOptions {
  wsUrl: string
  token: string
  tags: Record<string, string>
  /** Tests only: where envelopes go instead of the network. */
  transport?: SentryNs.BrowserOptions['transport']
}

/** Fetch GET /config and start Sentry if it returns a DSN. Never throws; false means off. */
export async function startTelemetry(opts: StartOptions): Promise<boolean> {
  token = opts.token
  tags = { ...APP_TAGS, ...opts.tags }
  let cfg: SentryConfig | null
  try {
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), CONFIG_TIMEOUT_MS)
    const res = await fetch(configUrl(opts.wsUrl), {
      headers: token ? { authorization: `Bearer ${token}` } : {},
      signal: ctl.signal,
    }).finally(() => clearTimeout(timer))
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    cfg = parseConfig(((await res.json()) as { sentry?: unknown }).sentry)
  } catch (err) {
    log('Sentry off: no /config', String(err))
    return false
  }
  if (!cfg) {
    log('Sentry off: /config has no DSN')
    return false
  }
  try {
    const mod = await import('./sentry-sdk')
    const out = <T>(kind: string, v: T): T => {
      const clean = scrub(v, token)
      if (debug()) log('sentry', kind, JSON.stringify(clean))
      return clean
    }
    mod.init({
      dsn: cfg.dsn,
      environment: cfg.environment,
      release: `floor-sense-glasses@${APP_VERSION}`,
      tracesSampleRate: cfg.tracesSampleRate,
      enableLogs: true,
      sendDefaultPii: false,
      // Console breadcrumbs would carry our [fs] lines, which include card and draft text.
      integrations: [mod.breadcrumbsIntegration({ console: false, history: false })],
      beforeBreadcrumb: b => (b.category === 'console' ? null : scrub(b, token)),
      beforeSend: e => out('event', e),
      beforeSendTransaction: e => out('transaction', e),
      beforeSendLog: l => out('log', l),
      initialScope: { tags },
      ...(opts.transport ? { transport: opts.transport } : {}),
    })
    S = mod
  } catch (err) {
    log('Sentry off: init failed', String(err))
    return false
  }
  for (const c of early.splice(0)) S.addBreadcrumb({ ...c, level: 'info' })
  log('Sentry on', cfg.environment)
  return true
}

export function setTags(next: Record<string, string>): void {
  tags = { ...tags, ...next }
  S?.setTags(next)
}

export function crumb(category: string, message: string, data?: Data): void {
  const c = data ? { category, message, data } : { category, message }
  if (S) S.addBreadcrumb({ ...c, level: 'info' })
  else if (early.push(c) > 100) early.shift()
}

/** A Sentry Log (numbers and states only). */
export function logInfo(message: string, attributes?: Data): void {
  S?.logger.info(message, attributes)
}

/** Send what is queued before the WebView is hidden or closed. */
export function flush(): void {
  void S?.flush(1000)
}

/** The last gesture or voice command, so a clip span knows what started it. */
export function noteInput(how: string): void {
  lastInput = { how, at: Date.now() }
}

// Clip: one transaction from the clip leaving (swipe back, "verity clip", Controls) to the order
// card on the lens, with children `clip -> order card` and `clip -> summary`.

function endClip(status: 'ok' | 'deadline_exceeded', at = Date.now()): void {
  if (!clip || !S) return
  clearTimeout(clip.timer)
  if (status !== 'ok') clip.root.setStatus({ code: 2, message: status })
  clip.root.end(at)
  clip = null
}

export function clipStarted(captureId: string, seconds: number, hasTable: boolean): void {
  crumb('clip', 'clip sent', { captureId, seconds, hasTable })
  if (!S) return
  const Sn = S
  endClip('deadline_exceeded')
  const now = Date.now()
  const trigger = lastInput && now - lastInput.at < TRIGGER_MS ? lastInput.how : 'other'
  const root = Sn.startNewTrace(() =>
    Sn.startInactiveSpan({
      name: 'clip -> order card',
      op: 'ui.clip',
      forceTransaction: true,
      startTime: now,
      attributes: { trigger, 'clip.seconds': seconds, 'clip.has_table': hasTable },
    }),
  )
  clip = { id: captureId, root, start: now, trigger, orderAt: null, timer: setTimeout(() => endClip('deadline_exceeded'), CLIP_SPAN_MAX_MS) }
}

export function clipShown(captureId: string | null, what: 'order' | 'summary'): void {
  if (!S || !clip || clip.id !== captureId) return
  const Sn = S
  const c = clip
  const now = Date.now()
  Sn.withActiveSpan(c.root, () =>
    Sn.startInactiveSpan({ name: what === 'order' ? 'clip -> order card' : 'clip -> summary', op: `ui.clip.${what}`, startTime: c.start }),
  ).end(now)
  logInfo(`clip -> ${what} on glasses`, { ms: now - c.start, trigger: c.trigger })
  if (what === 'summary') return endClip('ok', now)
  c.orderAt = now
  clearTimeout(c.timer)
  c.timer = setTimeout(() => endClip('ok', c.orderAt ?? Date.now()), SUMMARY_GRACE_MS)
}

// task.assigned -> the card redrawn on the lens; continues the backend trace when the frame has one.

function endCard(c: CardSpan, shown: boolean, at = Date.now()): void {
  clearTimeout(c.timer)
  c.span.setAttribute('shown', shown)
  c.span.end(at)
  cards = cards.filter(x => x !== c)
}

export function taskAssigned(msg: TaskAssigned): void {
  if (!S) return
  const Sn = S
  const trace = traceOf(msg)
  const start = () =>
    Sn.startInactiveSpan({
      name: 'task.assigned -> card',
      op: 'ui.card',
      forceTransaction: true,
      attributes: { 'task.id': msg.task.id, 'task.kind': msg.task.kind, continued: trace !== null },
    })
  const span = trace ? Sn.continueTrace({ sentryTrace: trace.sentryTrace, baggage: trace.baggage }, start) : Sn.startNewTrace(start)
  const c: CardSpan = { span, start: Date.now(), timer: setTimeout(() => endCard(c, false), CARD_SPAN_MAX_MS) }
  cards.push(c)
}

/** The card isn't on screen (manager role, draft, Controls): end the spans now. */
export function cardNotShown(onTop: boolean): void {
  for (const c of cards) {
    c.span.setAttribute('on_top', onTop)
    endCard(c, false)
  }
}

/**
 * Ends pending card spans when a write to the main text container that began after them lands.
 * Wraps the bridge's two drawing calls; nothing else changes.
 */
export function watchLens(bridge: EvenAppBridge, mainId: number): void {
  const upgrade = bridge.textContainerUpgrade.bind(bridge)
  const rebuild = bridge.rebuildPageContainer.bind(bridge)
  const drawn = (began: number) => {
    const at = Date.now()
    for (const c of cards.slice()) if (c.start <= began) endCard(c, true, at)
  }
  bridge.textContainerUpgrade = async c => {
    const began = Date.now()
    const ok = await upgrade(c)
    if (c.containerID === mainId) drawn(began)
    return ok
  }
  bridge.rebuildPageContainer = async c => {
    const began = Date.now()
    const ok = await rebuild(c)
    drawn(began)
    return ok
  }
}
