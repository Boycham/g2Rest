import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  activeHolds,
  alertText,
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

test('fromSnapshot takes the pass from the snapshot, else keeps the previous one', () => {
  const prev = apply(emptyState(), { type: 'pass.state', plates: [], holds: [] }, 5)
  assert.deepEqual(fromSnapshot({}, prev).pass, { plates: [], holds: [], at: 5 })
  const snapPass = { type: 'pass.state', planner: 'priority', plates: [], holds: [], runs: [] }
  assert.deepEqual(fromSnapshot({ pass: snapPass }, prev, 9).pass, {
    planner: 'priority',
    plates: [],
    holds: [],
    runs: [],
    at: 9,
  })
})

test('activeHolds shows a course only once some of its plates are up', () => {
  const pass = {
    plates: [
      { table: 'T4', course: 'main', status: 'up' },
      { table: 'T4', course: 'main', status: 'waiting' },
      { table: 'T2', course: 'appetizer', status: 'waiting' },
    ],
    holds: [
      { table: 'T4', course: 'main', waitingOn: ['Duck'] },
      { table: 'T2', course: 'appetizer', waitingOn: ['Burrata'] },
    ],
  }
  assert.deepEqual(
    activeHolds(pass).map((hd) => hd.table),
    ['T4'],
  )
  assert.deepEqual(activeHolds(null), [])
})

test('alertText fills in the elapsed time and keeps ticking', () => {
  const s = fromSnapshot(
    { alerts: [{ id: 'a1', level: 'urgent', text: 'T4 run task unacknowledged {elapsed}', table: 'T4', sinceSec: 50 }] },
    emptyState(),
    0,
  )
  assert.equal(alertText(s.alerts.a1, 15_000), 'T4 run task unacknowledged 1m')
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

test('ticketRows sorts by course then seat and carries each plate status', () => {
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
  const pass = {
    plates: [
      { orderId: 'o1', line: 0, status: 'up' },
      { orderId: 'o1', line: 1, status: 'running' },
      { orderId: 'other', line: 2, status: 'up' },
    ],
  }
  const rows = ticketRows(order, menu, pass)
  assert.deepEqual(
    rows.map((r) => [r.index, r.course, r.plate]),
    [
      [2, 'appetizer', null],
      [1, 'appetizer', 'running'],
      [0, 'main', 'up'],
    ],
  )
})

test('ticketRows flags a dish that contains the seat allergen, and only for that seat', () => {
  const menu = { dishes: [{ name: 'Soup', course: 'appetizer', temperature: 'hot', allergens: ['dairy', 'gluten'] }] }
  const order = {
    orderId: 'o1',
    allergies: [{ allergen: 'DAIRY', seats: [2] }],
    lines: [
      { seat: 1, qty: 1, dish: 'Soup', alterations: [], flagged: [] },
      { seat: 2, qty: 1, dish: 'Soup', alterations: ['no cream'], flagged: [] },
    ],
  }
  const rows = ticketRows(order, menu, null)
  assert.deepEqual(
    rows.map((r) => [r.seat, r.conflicts]),
    [
      [1, []],
      [2, ['DAIRY']],
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
