import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  allergyText,
  apply,
  boardTasks,
  emptyState,
  fmtSince,
  fromSnapshot,
  itemsText,
  liveSince,
  seatAllergies,
  ticketRows,
} from './state.js'

const task = (id, state, extra = {}) => ({
  id,
  kind: 'RUN',
  table: 'T4',
  items: [],
  allergies: [],
  notes: [],
  state,
  assignee: 's1',
  createdAt: '2026-10-17T20:00:00+00:00',
  ...extra,
})

test('task.assigned then task.updated replaces the task and drops a stale backendState', () => {
  let s = fromSnapshot({ tasks: [{ ...task('t1', 'assigned'), backendState: 'sent' }] }, emptyState(), 0)
  s = apply(s, { type: 'task.assigned', task: task('t1', 'assigned') }, 1)
  assert.equal(s.tasks.t1.backendState, 'sent')
  s = apply(s, { type: 'task.updated', task: task('t1', 'accepted') }, 2)
  assert.equal(s.tasks.t1.state, 'accepted')
  assert.equal(s.tasks.t1.backendState, undefined)
})

test('apply never mutates the previous state', () => {
  const s0 = emptyState()
  const s1 = apply(s0, { type: 'task.assigned', task: task('t1', 'assigned') })
  assert.deepEqual(s0.tasks, {})
  assert.ok(s1.tasks.t1)
})

test('a cleared alert is removed', () => {
  let s = apply(emptyState(), { type: 'alert', id: 'a1', level: 'urgent', text: 'x', table: 'T4' })
  assert.ok(s.alerts.a1)
  s = apply(s, { type: 'alert', id: 'a1', level: 'urgent', text: '', table: 'T4', cleared: true })
  assert.equal(s.alerts.a1, undefined)
})

test('order.draft creates a draft and order.closed sets its status', () => {
  let s = apply(emptyState(), {
    type: 'order.draft',
    orderId: 'o1',
    captureId: 'c1',
    table: 'T2',
    lines: [{ seat: 1, qty: 1, dish: 'Burrata', alterations: [], flagged: [] }],
    allergies: [],
  })
  assert.equal(s.orders.o1.status, 'draft')
  assert.equal(s.orders.o1.type, undefined)
  s = apply(s, { type: 'order.closed', orderId: 'o1', status: 'fired' })
  assert.equal(s.orders.o1.status, 'fired')
})

test('order.closed for an unknown order is ignored', () => {
  const s = emptyState()
  assert.equal(apply(s, { type: 'order.closed', orderId: 'nope', status: 'fired' }), s)
})

test('fromSnapshot keeps the pass from the previous state', () => {
  const prev = apply(emptyState(), { type: 'pass.state', plates: [], holds: [] })
  assert.deepEqual(fromSnapshot({}, prev).pass, { plates: [], holds: [] })
})

test('liveSince ticks forward from when the table was received', () => {
  assert.equal(liveSince({ sinceSec: 10, at: 1_000 }, 4_500), 13)
  assert.equal(liveSince({ sinceSec: 10, at: 5_000 }, 1_000), 10)
})

test('fmtSince', () => {
  assert.equal(fmtSince(42), '42s')
  assert.equal(fmtSince(14 * 60 + 5), '14m')
  assert.equal(fmtSince(75 * 60), '1h 15m')
})

test('boardTasks puts open work first and done last', () => {
  const s = fromSnapshot({
    tasks: [task('done', 'done'), task('acc', 'accepted'), task('new', 'assigned')],
  })
  assert.deepEqual(
    boardTasks(s).map((t) => t.id),
    ['new', 'acc', 'done'],
  )
})

test('itemsText and allergyText', () => {
  assert.equal(
    itemsText([
      { qty: 2, dish: 'Halibut', seats: [1, 3] },
      { qty: 1, dish: 'Soup', seats: [] },
    ]),
    '2× Halibut, Soup',
  )
  assert.equal(allergyText([{ allergen: 'SHELLFISH', seats: [3] }, { allergen: 'DAIRY', seats: [] }]), 'SHELLFISH s3 · DAIRY')
  assert.equal(allergyText([]), '')
})

test('ticketRows sorts by course then seat and marks lines already up', () => {
  const menu = {
    dishes: [
      { name: 'Halibut', course: 'main', temperature: 'hot' },
      { name: 'Soup', course: 'appetizer', temperature: 'hot' },
    ],
  }
  const order = {
    orderId: 'o1',
    lines: [
      { seat: 2, qty: 1, dish: 'Halibut', alterations: [], flagged: [] },
      { seat: 3, qty: 1, dish: 'Soup', alterations: [], flagged: [] },
      { seat: 1, qty: 1, dish: 'Soup', alterations: [], flagged: [] },
    ],
  }
  const pass = { plates: [{ orderId: 'o1', line: 0 }, { orderId: 'other', line: 1 }] }
  const rows = ticketRows(order, menu, pass)
  assert.deepEqual(
    rows.map((r) => [r.index, r.course, r.up]),
    [
      [2, 'appetizer', false],
      [1, 'appetizer', false],
      [0, 'main', true],
    ],
  )
})

test('seatAllergies includes table-wide allergies', () => {
  const all = [
    { allergen: 'NUTS', seats: [2] },
    { allergen: 'DAIRY', seats: [] },
  ]
  assert.deepEqual(
    seatAllergies(all, 1).map((a) => a.allergen),
    ['DAIRY'],
  )
  assert.deepEqual(
    seatAllergies(all, 2).map((a) => a.allergen),
    ['NUTS', 'DAIRY'],
  )
})
