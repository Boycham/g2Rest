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

describe('order.closed', () => {
  it('accepts fired and cancelled, rejects anything else', () => {
    expect(parseBackendMessage(JSON.stringify({ type: 'order.closed', orderId: 'o1', status: 'fired' }))?.type).toBe('order.closed')
    expect(parseBackendMessage(JSON.stringify({ type: 'order.closed', orderId: 'o1', status: 'cancelled' }))).not.toBeNull()
    expect(parseBackendMessage(JSON.stringify({ type: 'order.closed', orderId: 'o1', status: 'sent' }))).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ type: 'order.closed', status: 'fired' }))).toBeNull()
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

describe('manager messages', () => {
  const table = { table: 'T4', status: 'waiting', sinceSec: 840, x: 1, y: 0, urgency: 4 }

  it('accepts a full floor.state and rejects tables without position or urgency', () => {
    const ok = { type: 'floor.state', tables: [table] }
    expect(parseBackendMessage(JSON.stringify(ok))).toEqual(ok)
    const noXY = { type: 'floor.state', tables: [{ table: 'T4', status: 'waiting', sinceSec: 840 }] }
    expect(parseBackendMessage(JSON.stringify(noXY))).toBeNull()
    const loud = { type: 'floor.state', tables: [{ ...table, urgency: 5 }] }
    expect(parseBackendMessage(JSON.stringify(loud))).toBeNull()
    const lost = { type: 'floor.state', tables: [{ ...table, status: 'lost' }] }
    expect(parseBackendMessage(JSON.stringify(lost))).toBeNull()
  })

  it('accepts alerts with and without the proposed fields', () => {
    const bare = { type: 'alert', id: 'a', level: 'info', text: 'VIP seated T7' }
    expect(parseBackendMessage(JSON.stringify(bare))).toEqual(bare)
    const full = { ...bare, level: 'urgent', text: 'T4 waiting {elapsed} on mains', table: 'T4', sinceSec: 840, cleared: false }
    expect(parseBackendMessage(JSON.stringify(full))).toEqual(full)
  })

  it('rejects malformed alerts', () => {
    const bare = { type: 'alert', id: 'a', level: 'info', text: 'x' }
    expect(parseBackendMessage(JSON.stringify({ ...bare, level: 'loud' }))).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ ...bare, sinceSec: -1 }))).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ ...bare, cleared: 'yes' }))).toBeNull()
    expect(parseBackendMessage(JSON.stringify({ ...bare, id: 3 }))).toBeNull()
  })
})
