import { describe, expect, it } from 'vitest'
import { parseBackendMessage, parseTaskList } from './parse'
import { makeTask } from './fixtures.test-helpers'

describe('parseBackendMessage', () => {
  it('accepts a valid task.assigned', () => {
    const msg = { type: 'task.assigned', task: makeTask() }
    expect(parseBackendMessage(JSON.stringify(msg))).toEqual(msg)
  })

  it('rejects malformed JSON, unknown types and bad tasks', () => {
    expect(parseBackendMessage('{nope')).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ type: 'task.exploded' }))).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ type: 'task.updated', task: { ...makeTask(), state: 'lost' } }))).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ type: 'task.assigned', task: { ...makeTask(), items: [{ qty: '2' }] } }))).toBeNull()
  })

  it('passes other backend types through by type', () => {
    expect(parseBackendMessage(JSON.stringify({ type: 'alert', id: 'a', level: 'warn', text: 'T4 waiting' }))?.type).toBe('alert')
  })
})

describe('parseTaskList', () => {
  it('round-trips a saved queue and rejects junk', () => {
    const q = [makeTask(), makeTask({ id: 't2', state: 'accepted' })]
    expect(parseTaskList(JSON.stringify(q))).toEqual(q)
    expect(parseTaskList('')).toBeNull()
    expect(parseTaskList('[{"id":1}]')).toBeNull()
  })
})
