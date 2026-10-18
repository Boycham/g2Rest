import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DONE_BEAT_MS, IDLE_MS, IdleBlank } from './idle'

describe('IdleBlank', () => {
  let changes: boolean[]
  let idle: IdleBlank
  beforeEach(() => {
    vi.useFakeTimers()
    changes = []
    idle = new IdleBlank(a => changes.push(a))
  })
  afterEach(() => vi.useRealTimers())

  it('blanks IDLE_MS after nothing holds it, and not before', () => {
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS - 1)
    expect(idle.awake).toBe(true)
    vi.advanceTimersByTime(1)
    expect(idle.awake).toBe(false)
    expect(changes).toEqual([false])
  })

  it('never blanks while held, and starts counting on release', () => {
    idle.update(true)
    vi.advanceTimersByTime(IDLE_MS * 3)
    expect(idle.awake).toBe(true)
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS)
    expect(idle.awake).toBe(false)
  })

  it('a hold (task arrives) wakes from blank at once', () => {
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS)
    idle.update(true)
    expect(changes).toEqual([false, true])
  })

  it('a wake (tap) shows it again for IDLE_MS', () => {
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS)
    idle.wake()
    expect(idle.awake).toBe(true)
    vi.advanceTimersByTime(IDLE_MS - 1)
    expect(idle.awake).toBe(true)
    vi.advanceTimersByTime(1)
    expect(changes).toEqual([false, true, false])
  })

  it('input (touch) restarts the countdown', () => {
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS - 100)
    idle.touch()
    vi.advanceTimersByTime(IDLE_MS - 100)
    expect(idle.awake).toBe(true)
    vi.advanceTimersByTime(100)
    expect(idle.awake).toBe(false)
  })

  it('touch while blank does not wake (a voice command that needs no screen)', () => {
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS)
    idle.touch()
    expect(idle.awake).toBe(false)
  })

  it('the last task done blanks after DONE_BEAT_MS', () => {
    idle.update(true)
    idle.update(false)
    idle.wake(DONE_BEAT_MS)
    vi.advanceTimersByTime(DONE_BEAT_MS)
    expect(idle.awake).toBe(false)
  })

  it('repeated updates while idle keep one timer, and a hold cancels it', () => {
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS / 2)
    idle.update(false)
    vi.advanceTimersByTime(IDLE_MS / 2)
    expect(idle.awake).toBe(false)
    idle.wake()
    idle.update(true)
    vi.advanceTimersByTime(IDLE_MS * 2)
    expect(changes).toEqual([false, true])
  })

  it('reset leaves no timer behind', () => {
    idle.update(false)
    idle.reset()
    vi.advanceTimersByTime(IDLE_MS * 2)
    expect(changes).toEqual([])
  })
})
