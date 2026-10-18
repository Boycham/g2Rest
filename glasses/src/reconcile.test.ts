import { describe, expect, it } from 'vitest'
import { applyBackendTask, markDone } from './reconcile'
import { tap } from './tasks'
import { makeTask } from './fixtures.test-helpers'

describe('applyBackendTask after a backend restart', () => {
  it('keeps a locally accepted card accepted and re-sends task.accept', () => {
    // Tap while offline: card is ACCEPTED, the accept sits in the outbox and gets lost.
    const accepted = tap([makeTask({ id: 'task-2', table: 'T4' })]).queue
    const r = applyBackendTask(accepted, [], makeTask({ id: 'task-2', table: 'T4', state: 'assigned' }))
    expect(r.queue.map(t => [t.id, t.state])).toEqual([['task-2', 'accepted']])
    expect(r.resend).toEqual([{ type: 'task.accept', taskId: 'task-2' }])
  })

  it('does not bring back a task done locally and re-sends accept + done', () => {
    const done = markDone([], 'task-1')
    const queue = [makeTask({ id: 'task-2' })]
    const r = applyBackendTask(queue, done, makeTask({ id: 'task-1', state: 'assigned' }))
    expect(r.queue.map(t => t.id)).toEqual(['task-2'])
    expect(r.done).toEqual(['task-1'])
    expect(r.resend).toEqual([
      { type: 'task.accept', taskId: 'task-1' },
      { type: 'task.done', taskId: 'task-1' },
    ])
  })

  it('re-sends only task.done when the backend already has it accepted', () => {
    const r = applyBackendTask([], ['task-1'], makeTask({ id: 'task-1', state: 'accepted' }))
    expect(r.resend).toEqual([{ type: 'task.done', taskId: 'task-1' }])
  })

  it('forgets a done id once the backend confirms it', () => {
    const r = applyBackendTask([], ['task-1', 'task-9'], makeTask({ id: 'task-1', state: 'done' }))
    expect(r.done).toEqual(['task-9'])
    expect(r.resend).toEqual([])
  })

  it('takes the backend state when it is further along', () => {
    const r = applyBackendTask([makeTask({ id: 'a' })], [], makeTask({ id: 'a', state: 'accepted' }))
    expect(r.queue[0].state).toBe('accepted')
    expect(r.resend).toEqual([])
  })

  it('caps the done list', () => {
    let done: readonly string[] = []
    for (let i = 0; i < 60; i++) done = markDone(done, `t${i}`)
    expect(done.length).toBe(50)
    expect(done.at(-1)).toBe('t59')
  })
})

describe('applyBackendTask after task.revert', () => {
  it('takes the un-accepted state as the answer instead of replaying the accept', () => {
    const t = makeTask({ id: 'r1' })
    const local = [{ ...t, state: 'accepted' as const }]
    const r = applyBackendTask(local, [], { ...t, state: 'assigned' }, true)
    expect(r.resend).toEqual([])
    expect(r.queue[0].state).toBe('assigned')
  })
})
