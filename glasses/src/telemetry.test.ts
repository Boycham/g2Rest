import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeTask } from './fixtures.test-helpers'
import {
  configUrl,
  clipShown,
  clipStarted,
  crumb,
  flush,
  frameData,
  parseConfig,
  scrub,
  scrubString,
  startTelemetry,
  taskAssigned,
  traceOf,
  watchLens,
} from './telemetry'
import type { EvenAppBridge } from '@evenrealities/even_hub_sdk'
import { version as APP_VERSION } from '../app.json'

const TOKEN = 'dev-token-123'

describe('telemetry helpers', () => {
  it('derives GET /config from the socket URL, without the token', () => {
    expect(configUrl('ws://localhost:8787/ws?token=x&role=server')).toBe('http://localhost:8787/config')
    expect(configUrl('wss://45-76-173-44.sslip.io/ws')).toBe('https://45-76-173-44.sslip.io/config')
  })

  it('filters the token query param and the token itself from every string', () => {
    expect(scrubString('wss://h/ws?token=abc&role=server', '')).toBe('wss://h/ws?token=[Filtered]&role=server')
    expect(scrubString(`Bearer ${TOKEN}`, TOKEN)).toBe('Bearer [Filtered]')
    const event = { request: { url: 'http://h/?a=1&token=zz' }, breadcrumbs: [{ data: { url: `ws://h/ws?token=${TOKEN}` } }], n: 3 }
    expect(scrub(event, TOKEN)).toEqual({
      request: { url: 'http://h/?a=1&token=[Filtered]' },
      breadcrumbs: [{ data: { url: 'ws://h/ws?token=[Filtered]' } }],
      n: 3,
    })
  })

  it('reads the sentry part of /config and treats anything else as off', () => {
    expect(parseConfig(null)).toBeNull()
    expect(parseConfig({ dsn: '' })).toBeNull()
    expect(parseConfig({ dsn: 'https://k@o1.ingest.sentry.io/2', environment: 'prod', tracesSampleRate: 0.5 })).toEqual({
      dsn: 'https://k@o1.ingest.sentry.io/2',
      environment: 'prod',
      tracesSampleRate: 0.5,
    })
    expect(parseConfig({ dsn: 'https://k@o1.ingest.sentry.io/2', tracesSampleRate: 7 })?.tracesSampleRate).toBe(1)
  })

  it('accepts only a well-formed CONTRACT 8.12 trace', () => {
    const sentryTrace = `${'a'.repeat(32)}-${'b'.repeat(16)}-1`
    expect(traceOf({ trace: { sentryTrace, baggage: 'sentry-trace_id=a' } })).toEqual({ sentryTrace, baggage: 'sentry-trace_id=a' })
    expect(traceOf({ trace: { sentryTrace: 'nope' } })).toBeNull()
    expect(traceOf({})).toBeNull()
  })

  it('keeps ids and states of a frame, never its dishes, notes or words', () => {
    const task = makeTask({ notes: ['anniversary'], allergies: [{ allergen: 'shellfish', seats: [3] }] })
    const data = frameData({ type: 'task.assigned', task })
    expect(data).toEqual({ type: 'task.assigned', 'task.id': 't1', 'task.kind': 'RUN', 'task.state': 'assigned', 'task.table': 'T12' })
    const unknown = frameData({ type: 'voice.unknown', words: 'bring the halibut' } as never)
    expect(JSON.stringify(unknown)).not.toContain('halibut')
  })
})

// Sentry init runs once per module, so every test after the first shares this transport.
const sent: string[] = []
const transport = () => ({
  send: async (envelope: unknown) => {
    sent.push(JSON.stringify(envelope))
    return {}
  },
  flush: async () => true,
})
const tick = (ms = 50) => new Promise(r => setTimeout(r, ms))
/** The transaction payloads (envelope item bodies) sent since the last call. */
function transactions(): Array<{ transaction: string; contexts: { trace: { trace_id: string; parent_span_id?: string; data: Record<string, unknown> } }; spans: Array<{ description: string; op: string }> }> {
  const out = sent.flatMap(e => (JSON.parse(e) as [unknown, Array<[{ type: string }, unknown]>])[1]).filter(([h]) => h.type === 'transaction').map(([, body]) => body as never)
  sent.length = 0
  return out
}

describe('startTelemetry', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('runs without Sentry when /config is unreachable or has no DSN', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await startTelemetry({ wsUrl: 'ws://localhost:1/ws', token: TOKEN, tags: {} })).toBe(false)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ sentry: null }))))
    expect(await startTelemetry({ wsUrl: 'ws://localhost:1/ws', token: TOKEN, tags: {} })).toBe(false)
  })

  it('sends a scrubbed event with tags and our breadcrumbs, the token only as a header to /config', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ sentry: { dsn: 'https://key@o1.ingest.us.sentry.io/2', environment: 'test', tracesSampleRate: 1 } })),
    )
    vi.stubGlobal('fetch', fetchMock)
    crumb('gesture', 'swipe back', { where: 'server/card' })
    const on = await startTelemetry({ wsUrl: `ws://localhost:8787/ws?token=${TOKEN}`, token: TOKEN, tags: { role: 'server', staff: 's1' }, transport })
    expect(on).toBe(true)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://localhost:8787/config')
    expect(init.headers).toEqual({ authorization: `Bearer ${TOKEN}` })

    console.log('[fs] card upgrade "! SHELLFISH s3"')
    const { captureException } = await import('@sentry/browser')
    captureException(new Error(`socket failed ws://h/ws?token=${TOKEN}`))
    flush()
    await tick()
    const all = sent.join('\n')
    if (process.env.SHOW_SENTRY_PAYLOAD) console.log(all)
    expect(all).toContain('swipe back')
    expect(all).toContain('"role":"server"')
    expect(all).toContain(`"app_version":"${APP_VERSION}"`)
    expect(all).toContain('"even_hub_sdk":"0.0.16"')
    expect(all).not.toContain(TOKEN)
    expect(all).not.toContain('SHELLFISH')
  })

  it('times a swipe-back clip to the order card and then the summary in one transaction', async () => {
    transactions()
    const { noteInput } = await import('./telemetry')
    noteInput('swipe back')
    clipStarted('cap-1', 60, true)
    await tick(20)
    clipShown('cap-1', 'order')
    await tick(20)
    clipShown('cap-1', 'summary')
    flush()
    await tick()
    const [tx, ...rest] = transactions()
    expect(rest).toEqual([])
    expect(tx!.transaction).toBe('clip -> order card')
    expect(tx!.contexts.trace.data).toMatchObject({ trigger: 'swipe back', 'clip.seconds': 60, 'clip.has_table': true })
    expect(tx!.spans.map(s => s.op).sort()).toEqual(['ui.clip.order', 'ui.clip.summary'])
  })

  it('continues the backend trace from task.assigned until the card is drawn', async () => {
    transactions()
    const bridge = { textContainerUpgrade: vi.fn().mockResolvedValue(true), rebuildPageContainer: vi.fn().mockResolvedValue(true) }
    watchLens(bridge as unknown as EvenAppBridge, 1)
    const traceId = 'a'.repeat(32)
    taskAssigned({ type: 'task.assigned', task: makeTask({ id: 'task-9' }), trace: { sentryTrace: `${traceId}-${'b'.repeat(16)}-1` } })
    await (bridge as unknown as EvenAppBridge).textContainerUpgrade({ containerID: 1, containerName: 'main', content: 'RUN · T12' } as never)
    flush()
    await tick()
    const [tx] = transactions()
    expect(tx!.transaction).toBe('task.assigned -> card')
    expect(tx!.contexts.trace.trace_id).toBe(traceId)
    expect(tx!.contexts.trace.parent_span_id).toBe('b'.repeat(16))
    expect(tx!.contexts.trace.data).toMatchObject({ 'task.id': 'task-9', continued: true, shown: true })
    expect(JSON.stringify(tx)).not.toContain('T12')
  })
})
