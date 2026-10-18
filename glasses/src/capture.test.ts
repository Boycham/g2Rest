import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EvenAppBridge } from '@evenrealities/even_hub_sdk'
import type { OrderDraft } from './contract'
import { BUSY_TICK_MS } from './busy'
import { CaptureScreen } from './capture'
import type { BackendSocket } from './socket'

function setup() {
  const upgrades: { id: number; content: string }[] = []
  const bridge = {
    rebuildPageContainer: vi.fn(async () => true),
    textContainerUpgrade: vi.fn(async (u: { containerID: number; content: string }) => {
      upgrades.push({ id: u.containerID, content: u.content })
      return true
    }),
  }
  const socket = { send: vi.fn(), sendAudio: vi.fn() }
  const screen = new CaptureScreen(bridge as unknown as EvenAppBridge, socket as unknown as BackendSocket, () => {})
  return { screen, bridge, upgrades, socket }
}

const draft = (over: Partial<OrderDraft> = {}): OrderDraft => ({
  type: 'order.draft',
  orderId: 'o1',
  captureId: '',
  table: 'T4',
  lines: [{ seat: 1, dish: 'halibut', qty: 1, alterations: [], flagged: [] }],
  allergies: [],
  status: 'draft',
  pending: [],
  voice: 'idle',
  notice: null,
  ...over,
})

async function beat(n = 1) {
  for (let i = 0; i < n; i++) await vi.advanceTimersByTimeAsync(BUSY_TICK_MS)
}

describe('CaptureScreen busy line', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance', 'Date'] })
    ;(globalThis as { window?: unknown }).window = globalThis
  })
  afterEach(() => vi.useRealTimers())

  it('animates processing, then summary, in the bar only, then stops', async () => {
    const { screen, bridge, upgrades, socket } = setup()
    screen.setOnline(true)
    await screen.enter()
    expect(screen.sendClip([new ArrayBuffer(3200)])).toBe(true)
    const id = socket.send.mock.calls[0][0].captureId as string
    await beat(3)
    const bars = upgrades.filter(u => u.id === 2).map(u => u.content)
    expect(bars.slice(0, 4)).toEqual(['Verity: processing.', 'Verity: processing..', 'Verity: processing...', 'Verity: processing.'])
    const mainBefore = upgrades.filter(u => u.id !== 2).length
    await beat(2)
    expect(upgrades.filter(u => u.id !== 2).length).toBe(mainBefore)

    screen.onDraft(draft({ captureId: id }))
    await beat(1)
    expect(upgrades.at(-1)?.content).toMatch(/summary\.+$/)

    upgrades.length = 0
    screen.onDraft(draft({ captureId: id, summary: 'Anniversary, unhurried.' }))
    await beat(1)
    const n = upgrades.length
    await beat(5)
    expect(upgrades.length).toBe(n)
    expect(upgrades.filter(u => u.id === 2).at(-1)?.content).not.toMatch(/summary|processing/)
    expect(bridge.rebuildPageContainer).toHaveBeenCalledTimes(1)
  })

  it('stops on the clip timeout and shows VOICE OFFLINE', async () => {
    const { screen, upgrades } = setup()
    screen.setOnline(true)
    await screen.enter()
    screen.sendClip([new ArrayBuffer(3200)])
    await vi.advanceTimersByTimeAsync(30_000)
    expect(upgrades.filter(u => u.id !== 2).at(-1)?.content).toContain('VOICE OFFLINE')
    const n = upgrades.length
    await beat(5)
    expect(upgrades.length).toBe(n)
    expect(upgrades.filter(u => u.id === 2).at(-1)?.content.trim()).toBe('')
  })

  it('lets summary go quietly when the talk agent never answers', async () => {
    const { screen, upgrades, socket } = setup()
    screen.setOnline(true)
    await screen.enter()
    screen.sendClip([new ArrayBuffer(3200)])
    screen.onDraft(draft({ captureId: socket.send.mock.calls[0][0].captureId }))
    await beat(1)
    expect(upgrades.at(-1)?.content).toMatch(/summary/)
    await vi.advanceTimersByTimeAsync(16_000)
    expect(upgrades.filter(u => u.id === 2).at(-1)?.content).not.toMatch(/summary/)
  })

  it('shows processing while Gemini maps words', async () => {
    const { screen, upgrades } = setup()
    screen.setOnline(true)
    await screen.enter()
    screen.setMapping(true)
    await beat(1)
    expect(upgrades.at(-1)).toEqual({ id: 2, content: 'Verity: processing..' })
    screen.setMapping(false)
    await beat(1)
    expect(upgrades.at(-1)?.content.trim()).toBe('')
  })
})
