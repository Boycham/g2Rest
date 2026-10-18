import { describe, expect, it } from 'vitest'
import { tap, upsertTask } from './tasks'
import { makeTask } from './fixtures.test-helpers'

describe('upsertTask', () => {
  it('appends new open tasks in arrival order', () => {
    const q = upsertTask(upsertTask([], makeTask({ id: 'a' })), makeTask({ id: 'b' }))
    expect(q.map(t => t.id)).toEqual(['a', 'b'])
  })

  it('replaces a known task in place', () => {
    const q = [makeTask({ id: 'a' }), makeTask({ id: 'b' })]
    const next = upsertTask(q, makeTask({ id: 'a', table: 'T4' }))
    expect(next.map(t => t.table)).toEqual(['T4', 'T12'])
  })

  it('removes a task the backend marks done or bounced', () => {
    const q = [makeTask({ id: 'a' }), makeTask({ id: 'b' })]
    expect(upsertTask(q, makeTask({ id: 'a', state: 'done' })).map(t => t.id)).toEqual(['b'])
    expect(upsertTask(q, makeTask({ id: 'b', state: 'bounced' })).map(t => t.id)).toEqual(['a'])
  })

  it('ignores a closed task it never had', () => {
    const q = [makeTask({ id: 'a' })]
    expect(upsertTask(q, makeTask({ id: 'z', state: 'done' }))).toBe(q)
  })
})

describe('tap', () => {
  it('does nothing on an empty queue', () => {
    expect(tap([])).toEqual({ queue: [], send: null })
  })

  it('accepts the current card first', () => {
    const r = tap([makeTask({ id: 'a' }), makeTask({ id: 'b' })])
    expect(r.send).toEqual({ type: 'task.accept', taskId: 'a' })
    expect(r.queue.map(t => [t.id, t.state])).toEqual([
      ['a', 'accepted'],
      ['b', 'assigned'],
    ])
  })

  it('marks it done on the second tap and reveals the next card', () => {
    const accepted = tap([makeTask({ id: 'a' }), makeTask({ id: 'b' })]).queue
    const r = tap(accepted)
    expect(r.send).toEqual({ type: 'task.done', taskId: 'a' })
    expect(r.queue.map(t => [t.id, t.state])).toEqual([['b', 'assigned']])
  })

  it('does not mutate the previous queue', () => {
    const q = [makeTask({ id: 'a' })]
    tap(q)
    expect(q[0].state).toBe('assigned')
  })
})
