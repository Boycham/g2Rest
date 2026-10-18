import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  alertTask,
  alertTasks,
  board,
  card,
  clock,
  clock2,
  hms,
  openQuestions,
  rerouteTarget,
  routingLog,
  shiftLeft,
  staffRows,
  tableSpots,
  tableTone,
  timelines,
} from '../src/dashboard/model.js'

const floor = {
  restaurant: 'Demo',
  sections: [
    { id: 'A', server: 's1' },
    { id: 'B', server: 's2' },
  ],
  servers: [
    { id: 's1', name: 'Ava', sections: ['A'] },
    { id: 's2', name: 'Ben', sections: ['B'] },
  ],
  manager: { id: 'm1', name: 'Dana' },
  tables: [
    { id: 'T1', section: 'A', seats: 2, x: 0, y: 0 },
    { id: 'T4', section: 'A', seats: 6, x: 9, y: 0 },
    { id: 'T5', section: 'B', seats: 2, x: 0, y: 4 },
  ],
}
const T0 = Date.parse('2026-10-18T12:00:00Z')
let seq = 0
// An event-log entry as GET /events returns it: wall-clock ISO `at`, monotonic data.at (s).
const ev = (sec, type, taskId, extra = {}) => ({
  seq: ++seq,
  at: new Date(T0 + sec * 1000).toISOString(),
  type: `task.${type}`,
  data: { taskId, kind: 'CHECK', table: 'T4', at: 1000 + sec, ...extra },
})
const task = (id, state, assignee, extra = {}) => ({
  id,
  kind: 'CHECK',
  table: 'T4',
  items: [],
  allergies: [],
  notes: [],
  state,
  assignee,
  createdAt: new Date(T0).toISOString(),
  ...extra,
})
const ctx = (now, extra = {}) => ({ floor, now: T0 + now * 1000, escalationSec: 30, ...extra })

test('clocks', () => {
  assert.equal(clock(62), '1:02')
  assert.equal(clock(3725), '1:02:05')
  assert.equal(clock2(168), '02:48')
  assert.equal(hms(9672), '02:41:12')
  assert.equal(shiftLeft(new Date(2026, 9, 18, 22, 0, 0).getTime(), '23:00'), 3600)
  assert.equal(shiftLeft(new Date(2026, 9, 18, 23, 30, 0).getTime(), '23:00'), 23.5 * 3600)
})

test('a task through its life: waiting with a ring, accepted, done', () => {
  const evs = [
    ev(0, 'queued', 't1', { reason: 'created', assignee: 's1' }),
    ev(1, 'sent', 't1', { reason: 'delivered', assignee: 's1' }),
  ]
  let c = card(task('t1', 'assigned', 's1'), timelines(evs).get('t1'), ctx(13))
  assert.equal(c.column, 'waiting')
  assert.equal(c.variant, 'waiting')
  assert.equal(c.subtitle, 'Ava · waiting to accept')
  assert.equal(c.ring.left, 18)

  evs.push(ev(43, 'accepted', 't1', { reason: 'task.accept', assignee: 's1' }))
  c = card(task('t1', 'accepted', 's1'), timelines(evs).get('t1'), ctx(85))
  assert.equal(c.column, 'accepted')
  assert.equal(c.subtitle, 'Ava · accepted 0:42 ago')

  evs.push(ev(211, 'done', 't1', { reason: 'task.done', assignee: 's1' }))
  c = card(task('t1', 'done', 's1'), timelines(evs).get('t1'), ctx(300))
  assert.equal(c.column, 'done')
  assert.equal(c.subtitle, 'Ava · done in 02:48')
})

test('over the limit, or passed on after no accept, is escalated', () => {
  const evs = [ev(0, 'queued', 't2', { reason: 'created', assignee: 's2' }), ev(0, 'sent', 't2', { assignee: 's2' })]
  let c = card(task('t2', 'assigned', 's2'), timelines(evs).get('t2'), ctx(62))
  assert.equal(c.variant, 'escalated')
  assert.equal(c.ring.left, -32)
  assert.equal(c.subtitle, 'Ben · no accept')

  evs.push(
    ev(30, 'escalated', 't2', { reason: 'no accept in time', assignee: 's2' }),
    ev(30, 'queued', 't2', { reason: 'after escalated from s2', assignee: 's1' }),
    ev(30, 'sent', 't2', { assignee: 's1' }),
  )
  c = card(task('t2', 'assigned', 's1'), timelines(evs).get('t2'), ctx(35))
  assert.equal(c.variant, 'escalated')
  assert.equal(c.subtitle, "Ben didn't accept · now Ava")
  assert.equal(c.ring.left, 25)
})

test('bounce, handoff, manager reroute, revert and offline glasses', () => {
  const base = [ev(0, 'queued', 't3', { reason: 'created', assignee: 's1' }), ev(0, 'sent', 't3', { assignee: 's1' })]
  const moved = (reason) => [
    ...base,
    ev(5, 'bounced', 't3', { reason, assignee: 's1' }),
    ev(5, 'queued', 't3', { reason: 'after bounced from s1', assignee: 's2' }),
    ev(5, 'sent', 't3', { assignee: 's2' }),
  ]
  const at = (evs) => card(task('t3', 'assigned', 's2'), timelines(evs).get('t3'), ctx(10))
  assert.deepEqual([at(moved('task.bounce')).variant, at(moved('task.bounce')).subtitle], ['bounced', 'Ava bounced · now Ben'])
  assert.equal(at(moved('task.handoff to s2')).subtitle, 'Ava handed off · Ben')
  assert.deepEqual([at(moved('manager reroute to s2')).variant, at(moved('manager reroute to s2')).subtitle], ['waiting', 'Rerouted from Ava · Ben'])
  assert.equal(at(moved('revert handoff by s2')).variant, 'reverted')

  const offline = [ev(0, 'queued', 't4', { reason: 'created', assignee: 'm1' })]
  const c = card(task('t4', 'assigned', 'm1'), timelines(offline).get('t4'), ctx(3))
  assert.equal(c.column, 'unassigned')
  assert.equal(c.subtitle, "Routing… Dana's glasses are offline")
})

test('board: waiting most urgent first; done newest first; table tone from the top card', () => {
  const evs = [
    ev(0, 'queued', 'a', { reason: 'created', assignee: 's1' }),
    ev(0, 'sent', 'a', { assignee: 's1' }),
    ev(20, 'queued', 'b', { reason: 'created', assignee: 's1', table: 'T1' }),
    ev(20, 'sent', 'b', { assignee: 's1', table: 'T1' }),
  ]
  const tasks = { a: task('a', 'assigned', 's1'), b: task('b', 'assigned', 's1', { table: 'T1' }) }
  const cols = board(tasks, timelines(evs), ctx(25, { alertedTasks: new Set() }))
  assert.deepEqual(
    cols.waiting.map((c) => c.id),
    ['a', 'b'],
  )
  assert.equal(tableTone('T1', cols).tone, 'waiting')
  assert.equal(tableTone('T5', cols).tone, 'idle')
  const late = board(tasks, timelines(evs), ctx(40, { alertedTasks: new Set() }))
  assert.equal(late.waiting[0].variant, 'escalated')
  assert.equal(tableTone('T4', late).tone, 'escalated')
})

test('routing log reads like a sentence, newest first, without "delivered" noise', () => {
  const evs = [
    ev(0, 'queued', 'x', { reason: 'created', assignee: 's1' }),
    ev(0, 'sent', 'x', { reason: 'delivered', assignee: 's1' }),
    ev(9, 'bounced', 'x', { reason: 'manager reroute to s2', assignee: 's1' }),
    ev(9, 'queued', 'x', { reason: 'after bounced from s1', assignee: 's2' }),
  ]
  const log = routingLog(evs, floor)
  assert.deepEqual(
    log.map((e) => [e.title, e.reason]),
    [
      ['Check on table · T4 → Ben', 'Moved on after bounced from Ava'],
      ['Ava passed on Check on table · T4', 'Rerouted from the dashboard'],
      ['Check on table · T4 → Ava', 'New task, routed by section and load'],
    ],
  )
})

test('alerts find their task from the log or the id; unknown kinds have none', () => {
  const tasks = { 'task-1a2b3c': task('task-1a2b3c', 'accepted', 's1') }
  const links = alertTasks([{ seq: 1, at: '', type: 'alert.raised', data: { alertId: 'slow-task-1a2b3c', taskId: 'task-1a2b3c' } }])
  assert.equal(alertTask({ id: 'slow-task-1a2b3c' }, links, tasks), 'task-1a2b3c')
  assert.equal(alertTask({ id: 'unacked-task-1a2b3c' }, new Map(), tasks), 'task-1a2b3c')
  assert.equal(alertTask({ id: '86-halibut' }, links, tasks), null)
  assert.equal(alertTask({ id: 'vip-T4' }, links, tasks), null)
})

test('reroute goes to an online server with the fewest open tasks, never the holder', () => {
  const stats = { servers: [{ id: 's1', open: [] }, { id: 's2', open: [1, 2] }] }
  assert.equal(rerouteTarget(task('t', 'assigned', 's1'), floor, stats, new Set(['s1', 's2'])).name, 'Ben')
  const three = { ...floor, servers: [...floor.servers, { id: 's3', name: 'Chi', sections: [] }] }
  const st3 = { servers: [...stats.servers, { id: 's3', open: [1] }] }
  assert.equal(rerouteTarget(task('t', 'assigned', 's1'), three, st3, new Set(['s1', 's2', 's3'])).name, 'Chi')
  assert.equal(rerouteTarget(task('t', 'assigned', 's1'), three, st3, new Set(['s2'])).name, 'Ben')
})

test('diner questions the menu could not answer, and staff rows', () => {
  const orders = {
    o1: { orderId: 'o1', table: 'T4', lines: [], answers: [{ seat: 2, q: 'Is the broth vegan?', a: '', known: false }, { q: 'Spicy?', a: 'Mild', known: true }], uncertain: ['seat 3 drink'] },
    o2: { orderId: 'o2', table: 'T5', status: 'cancelled', lines: [], answers: [{ q: 'x', a: '', known: false }] },
  }
  assert.deepEqual(
    openQuestions(orders).map((q) => [q.table, q.seat, q.q]),
    [
      ['T4', 2, 'Is the broth vegan?'],
      ['T4', null, 'seat 3 drink'],
    ],
  )
  const rows = staffRows(floor, { servers: [{ id: 's1', done: 3, avgSec: 168, open: [] }] }, new Set(['s1']))
  assert.deepEqual(
    rows.map((r) => [r.name, r.role, r.online, r.done]),
    [
      ['Ava', 'server', true, 3],
      ['Ben', 'server', false, 0],
      ['Dana', 'manager', false, 0],
    ],
  )
})

test('table spots spread the /floor grid over the map', () => {
  const spots = tableSpots(floor)
  assert.deepEqual(
    spots.map((s) => [s.id, +s.fx.toFixed(2), +s.fy.toFixed(2)]),
    [
      ['T1', 0.15, 0.36],
      ['T4', 0.85, 0.36],
      ['T5', 0.15, 0.74],
    ],
  )
})
