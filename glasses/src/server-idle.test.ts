import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BackendMessage, Task } from './contract'
import type { HudContext } from './hud'
import { DONE_BEAT_MS, IDLE_MS } from './idle'

vi.stubGlobal('location', { search: '' })
const { ServerHud } = await import('./server')

type Content = { containerTotalNum: number; textObject: { content: string; textColor: number }[] }

function fakeHud(queue: Task[] = []) {
  const rebuilds: Content[] = []
  const upgrades: string[] = []
  const sent: { type: string }[] = []
  const bridge = {
    rebuildPageContainer: async (p: Content) => (rebuilds.push(p), true),
    textContainerUpgrade: async (u: { content: string }) => (upgrades.push(u.content), true),
    audioControl: async () => true,
    setLocalStorage: async () => true,
    getLocalStorage: async () => '',
  }
  const socket = { send: (m: { type: string }) => sent.push(m), sendAudio: () => {} }
  const ctx = {
    bridge,
    socket,
    status: () => 'online',
    active: () => true,
    syncPhone: () => {},
  } as unknown as HudContext
  const hud = new ServerHud(ctx, queue, [])
  const last = () => rebuilds.at(-1)!
  const isBlank = (p: Content) => p.containerTotalNum === 1 && p.textObject[0]!.content.trim() === '' && p.textObject[0]!.textColor === 0
  return { hud, rebuilds, upgrades, sent, last, isBlank }
}

const task = (id: string, state: Task['state'] = 'assigned'): Task => ({
  id,
  kind: 'RUN',
  table: 'T12',
  items: [{ qty: 2, dish: 'halibut', seats: [1, 3] }],
  allergies: [],
  notes: [],
  state,
})
const assigned = (t: Task): BackendMessage => ({ type: 'task.assigned', task: t })

describe('server HUD idle blank', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('starts on the Task tab, then blanks after IDLE_MS with nothing to do', () => {
    const f = fakeHud()
    f.hud.startPage()
    expect(f.hud.screen()).toBe('card')
    vi.advanceTimersByTime(IDLE_MS)
    expect(f.hud.screen()).toBe('blank')
    expect(f.isBlank(f.last())).toBe(true)
  })

  it('a tap wakes to the Task tab with No tasks, then blanks again', () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onTap()
    expect(f.hud.screen()).toBe('card')
    expect(f.last().containerTotalNum).toBe(4)
    expect(f.last().textObject.at(-1)!.content.split('\n')[0]).toBe('No tasks')
    expect(f.last().textObject.map(t => t.content).slice(0, 3)).toEqual(['Controls', 'Queue', 'Task'])
    expect(f.sent).toEqual([])
    vi.advanceTimersByTime(IDLE_MS)
    expect(f.hud.screen()).toBe('blank')
  })

  it('task.assigned wakes it and holds it while the task is open', () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onMessage(assigned(task('t1')))
    expect(f.hud.screen()).toBe('card')
    expect(f.last().textObject.at(-1)!.content).toContain('T12')
    vi.advanceTimersByTime(IDLE_MS * 5)
    expect(f.hud.screen()).toBe('card')
  })

  it('the last task done shows Done and blanks after DONE_BEAT_MS', async () => {
    const f = fakeHud([task('t1', 'accepted')])
    f.hud.startPage()
    f.hud.onTap()
    expect(f.sent.at(-1)!.type).toBe('task.done')
    await vi.advanceTimersByTimeAsync(0)
    expect(f.upgrades.at(-1)!.split('\n')[0]).toBe('Done')
    await vi.advanceTimersByTimeAsync(DONE_BEAT_MS - 1)
    expect(f.hud.screen()).toBe('card')
    await vi.advanceTimersByTimeAsync(1)
    expect(f.hud.screen()).toBe('blank')
  })

  it('done with more queued stays on the next task', () => {
    const f = fakeHud([task('t1', 'accepted'), task('t2')])
    f.hud.startPage()
    f.hud.onTap()
    vi.advanceTimersByTime(IDLE_MS * 2)
    expect(f.hud.screen()).toBe('card')
  })

  it('swipe back while blank still clips and opens the draft', async () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onSwipeDown()
    expect(f.hud.screen()).toBe('draft')
    await vi.advanceTimersByTimeAsync(IDLE_MS * 2)
    expect(f.hud.screen()).toBe('draft')
  })

  it('an 86 alert wakes it for IDLE_MS', () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onMessage({ type: 'alert', id: 'a86', kind: '86', level: 'info', text: '86 halibut' } as never)
    expect(f.hud.screen()).toBe('card')
    expect(f.last().textObject.at(-1)!.content).toContain('86 halibut')
    vi.advanceTimersByTime(IDLE_MS)
    expect(f.hud.screen()).toBe('blank')
  })

  it('verity menu and verity ramp wake it; verity done (nothing to do) stays blank', () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onVoiceCommand({ type: 'voice.command', intent: 'done' } as never)
    expect(f.hud.screen()).toBe('blank')
    f.hud.onVoiceCommand({ type: 'voice.command', intent: 'menu' } as never)
    expect(f.hud.screen()).toBe('controls')
    vi.advanceTimersByTime(IDLE_MS)
    expect(f.hud.screen()).toBe('blank')
    f.hud.onVoiceCommand({ type: 'voice.command', intent: 'ramp' } as never)
    expect(f.hud.screen()).toBe('card')
    expect(f.last().containerTotalNum).toBe(4)
  })

  it('the processing indicator holds the screen until its answer', () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onMessage({ type: 'voice.mapping', words: 'something' } as never)
    expect(f.hud.screen()).toBe('card')
    vi.advanceTimersByTime(4000)
    expect(f.hud.screen()).toBe('card')
  })

  it('a spoken request wakes it and holds its confirm line until the tap sends it', () => {
    const f = fakeHud()
    f.hud.startPage()
    vi.advanceTimersByTime(IDLE_MS)
    f.hud.onMessage({ type: 'voice.request', table: 'T2', source: 'clip', kind: 'CHECK', status: 'check' } as never)
    expect(f.hud.screen()).toBe('card')
    vi.advanceTimersByTime(IDLE_MS * 2)
    expect(f.hud.screen()).toBe('card')
    expect(f.last().textObject.at(-1)!.content).toContain('Request: CHECK T2? tap')
    f.hud.onTap()
    expect(f.sent).toEqual([{ type: 'table.status', table: 'T2', status: 'check' }])
    vi.advanceTimersByTime(IDLE_MS)
    expect(f.hud.screen()).toBe('blank')
  })
})
