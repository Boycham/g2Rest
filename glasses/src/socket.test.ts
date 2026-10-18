import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendUrl } from './backend-url'
import { BackendSocket } from './socket'

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
    const socket = new BackendSocket(backendUrl(base, 'manager', 'dev'), { onMessage() {}, onStatus() {} })
    socket.connect()
    expect(params(FakeWebSocket.opened[0]!)).toMatchObject({ role: 'manager', staff: 'm1', token: 'dev' })

    socket.redial(backendUrl(base, 'server', 'dev'))
    expect(FakeWebSocket.opened).toHaveLength(2)
    expect(FakeWebSocket.opened[0]!.readyState).toBe(3)
    expect(params(FakeWebSocket.opened[1]!)).toMatchObject({ role: 'server', staff: 's1' })
    expect(socket.currentUrl).toBe(FakeWebSocket.opened[1]!.url)
  })
})
