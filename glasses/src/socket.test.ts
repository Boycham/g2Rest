import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendUrl } from './backend-url'
import type { Role } from './hud'
import { BackendSocket, retryDelay } from './socket'

class FakeWebSocket {
  static OPEN = 1
  static opened: FakeWebSocket[] = []
  readyState = 0
  binaryType = ''
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  onclose: ((ev: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly url: string) {
    FakeWebSocket.opened.push(this)
  }
  send(): void {}
  close(): void {
    this.readyState = 3
  }
}

const params = (ws: FakeWebSocket) => Object.fromEntries(new URL(ws.url).searchParams)

describe('role on connect', () => {
  beforeEach(() => {
    FakeWebSocket.opened = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })
  afterEach(() => vi.unstubAllGlobals())

  it("connects with the picker's role and redials with the new role on a switch", () => {
    const base = 'ws://localhost:8787/ws?role=server&staff=s1'
    let role: Role = 'manager'
    const socket = new BackendSocket(() => backendUrl(base, role, 'dev'), { onMessage() {}, onStatus() {} })
    socket.connect()
    expect(params(FakeWebSocket.opened[0]!)).toMatchObject({ role: 'manager', staff: 'm1', token: 'dev' })

    role = 'server'
    socket.reconnectNow()
    expect(FakeWebSocket.opened).toHaveLength(2)
    expect(FakeWebSocket.opened[0]!.readyState).toBe(3)
    expect(params(FakeWebSocket.opened[1]!)).toMatchObject({ role: 'server', staff: 's1' })
    expect(socket.currentUrl).toBe(FakeWebSocket.opened[1]!.url)
  })
})

describe('reconnect after a backend restart', () => {
  const base = 'ws://localhost:8787/ws'
  beforeEach(() => {
    FakeWebSocket.opened = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
  const drop = (ws: FakeWebSocket) => ws.onclose?.({ code: 1006 })
  const last = () => FakeWebSocket.opened[FakeWebSocket.opened.length - 1]!

  it('backs off by doubling, capped at 10 s, with jitter between half and all of the step', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 9].map(a => retryDelay(a, () => 1))).toEqual([
      500, 1000, 2000, 4000, 8000, 10000, 10000, 10000,
    ])
    expect([0, 1, 4, 5, 20].map(a => retryDelay(a, () => 0))).toEqual([250, 500, 4000, 5000, 5000])
    expect(retryDelay(3, () => 0.5)).toBe(3000)
  })

  it('retries with the URL for the role at retry time and resets the backoff once open', () => {
    let role: Role = 'server'
    const statuses: string[] = []
    const socket = new BackendSocket(() => backendUrl(base, role, 'dev'), {
      onMessage() {},
      onStatus: s => statuses.push(s),
    }, () => 1)
    socket.connect()
    last().onopen?.()
    drop(last())
    role = 'manager'

    const dialTimes: number[] = []
    for (let i = 0; i < 6; i++) {
      const before = FakeWebSocket.opened.length
      const start = Date.now()
      vi.advanceTimersToNextTimer()
      expect(FakeWebSocket.opened).toHaveLength(before + 1)
      dialTimes.push(Date.now() - start)
      drop(last())
    }
    expect(dialTimes).toEqual([500, 1000, 2000, 4000, 8000, 10000])
    for (const ws of FakeWebSocket.opened.slice(1)) expect(params(ws)).toMatchObject({ role: 'manager', staff: 'm1', token: 'dev' })

    vi.advanceTimersToNextTimer()
    last().onopen?.()
    expect(socket.online).toBe(true)
    drop(last())
    vi.advanceTimersByTime(499)
    const n = FakeWebSocket.opened.length
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.opened).toHaveLength(n + 1)
    expect(statuses).toContain('offline')
  })

  it('reconnectNow (foreground) dials at once with the current URL and drops the pending retry', () => {
    let staff = 's1'
    const socket = new BackendSocket(() => backendUrl(base, 'server', 'dev', staff), { onMessage() {}, onStatus() {} }, () => 1)
    socket.connect()
    drop(last())
    staff = 's2'
    socket.reconnectNow()
    expect(FakeWebSocket.opened).toHaveLength(2)
    expect(params(last())).toMatchObject({ role: 'server', staff: 's2' })
    vi.advanceTimersByTime(600)
    expect(FakeWebSocket.opened).toHaveLength(2)
  })
})
