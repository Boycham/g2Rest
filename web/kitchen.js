// Kitchen page: live tickets by course and seat, a "food up" button per dish (stands in for
// the ESP32 button), and the pass: held courses, plates up, and the runs the engine sent.
//
// "Food up" goes to POST /pass/up; the backend's planner decides when a run leaves and who
// takes it. This page never decides anything about runs.
import { api, chrome, h, live, startSentry, traced } from './client.js'
import {
  activeHolds,
  allergyText,
  apply,
  emptyState,
  fmtSince,
  fromSnapshot,
  itemsText,
  liveSince,
  ticketRows,
  upReason,
  withAt,
} from './state.js'

const $ = (id) => document.getElementById(id)
const ui = chrome()
const COURSE_LABEL = { appetizer: 'APP', main: 'MAIN', dessert: 'DSRT' }
const PLATE_BUTTON = { waiting: 'Food up', up: 'Up', running: 'Running' }

let state = emptyState()
let menu = null
let floor = null

function staffName(id) {
  if (!id || !floor) return id ?? ''
  if (id === floor.manager.id) return floor.manager.name
  return floor.servers.find((s) => s.id === id)?.name ?? id
}

async function act(label, fn) {
  try {
    await traced(label, fn)
  } catch (e) {
    ui.error(`${label}: ${e.message}`)
  }
}

async function resync() {
  await act('Load state', async () => {
    state = fromSnapshot(await api('/state'), state)
    render()
  })
}

async function foodUp(order, row) {
  await act(`Food up ${order.table} ${row.dish}`, async () => {
    const pass = await api('/pass/up', { orderId: order.orderId, line: row.index })
    state = { ...state, pass: withAt(pass) }
    render()
  })
}

// ---------- render ----------

function ticket(order, { draft }) {
  const rows = ticketRows(order, menu, state.pass)
  const allergies = allergyText(order.allergies ?? [])
  return h(
    'div',
    { class: `ticket${draft ? ' draft' : ''}` },
    h(
      'header',
      {},
      h('strong', {}, order.table),
      h('span', { class: 'pill' }, order.status),
      h('span', { class: 'muted' }, staffName(order.owner)),
    ),
    allergies ? h('div', { class: 'allergy' }, `ALLERGY ${allergies}`) : null,
    rows.length ? null : h('div', { class: 'empty' }, 'No dishes yet'),
    rows.map((r) =>
      h(
        'div',
        { class: `line${r.plate === 'up' || r.plate === 'running' ? ' up' : ''}` },
        h('span', { class: 'course' }, COURSE_LABEL[r.course] ?? r.course),
        h(
          'div',
          {},
          h(
            'div',
            {},
            `S${r.seat} `,
            r.qty > 1 ? `${r.qty}× ` : '',
            h('span', { class: r.temperature === 'hot' ? 'temp-hot' : '' }, r.dish),
          ),
          r.conflicts.length
            ? h('div', { class: 'allergy' }, `CONTAINS ${r.conflicts.join(', ')}: seat ${r.seat} allergy`)
            : null,
          r.alterations.length ? h('div', { class: 'muted' }, r.alterations.join(', ')) : null,
          r.flagged.length ? h('div', { class: 'flagged' }, `flagged, not applied: ${r.flagged.join(', ')}`) : null,
        ),
        r.plate
          ? h('button', { disabled: r.plate !== 'waiting', onclick: () => foodUp(order, r) }, PLATE_BUTTON[r.plate])
          : null,
      ),
    ),
  )
}

function renderMode() {
  const planner = state.pass?.planner
  const mode = $('mode')
  mode.dataset.fifo = String(planner === 'fifo')
  mode.textContent =
    planner === 'fifo'
      ? 'Planner: FIFO baseline. Plates leave in the order they came up, 3 per runner, with no scoring or pairing.'
      : planner
        ? "Planner: priority. A run leaves when a table's whole course is up and a server is free; the best-scoring run goes first, and hot plates in one section ride together."
        : 'Loading the pass…'
}

function renderPass() {
  const pass = state.pass
  $('holds').replaceChildren(
    ...activeHolds(pass).map((hd) =>
      h('div', { class: 'hold' }, `${hd.table} ${hd.course} held for: ${hd.waitingOn.join(', ')}`),
    ),
  )
  const up = (pass?.plates ?? []).filter((p) => p.status === 'up').sort((a, b) => b.score - a.score)
  $('plates').replaceChildren(
    ...(up.length
      ? up.map((p) =>
          h(
            'div',
            { class: 'plate' },
            h('strong', {}, `${p.table} S${p.seat} `),
            h('span', { class: p.temperature === 'hot' ? 'temp-hot' : '' }, p.dish),
            h(
              'span',
              { class: 'muted' },
              ` · up ${fmtSince(liveSince({ sinceSec: p.upSec, at: pass.at }))} · score ${p.score.toFixed(1)} · `,
            ),
            upReason(pass, p) === 'held'
              ? h('span', { class: 'muted' }, 'held')
              : h('span', { class: 'flagged' }, 'needs a server'),
          ),
        )
      : [h('div', { class: 'empty' }, 'Nothing waiting at the pass.')]),
  )
  const runs = Object.values(state.tasks).filter((t) => t.kind === 'RUN' && t.state !== 'done')
  $('runs').replaceChildren(
    ...(runs.length
      ? runs.map((t) =>
          h(
            'div',
            { class: 'plate' },
            h('strong', {}, `${t.table} `),
            itemsText(t.items),
            ' ',
            h('span', { class: `pill ${t.state}` }, `${staffName(t.assignee)} · ${t.state}`),
            (t.notes ?? []).map((n) => h('div', { class: 'muted' }, n)),
          ),
        )
      : [h('div', { class: 'empty' }, 'No runs out.')]),
  )
}

function render() {
  if (!menu) return
  renderMode()
  const orders = Object.values(state.orders)
  const drafts = orders.filter((o) => o.status === 'draft')
  const fired = orders.filter((o) => o.status === 'fired')
  $('drafts').replaceChildren(
    ...(drafts.length
      ? drafts.map((o) => ticket(o, { draft: true }))
      : [h('div', { class: 'empty' }, 'No one is taking an order.')]),
  )
  $('tickets').replaceChildren(
    ...(fired.length
      ? fired.map((o) => ticket(o, { draft: false }))
      : [h('div', { class: 'empty' }, 'No tickets fired yet.')]),
  )
  renderPass()
}

// ---------- start ----------

async function start() {
  try {
    ;[menu, floor] = await Promise.all([api('/menu'), api('/floor')])
  } catch (e) {
    ui.error(`Could not load the menu: ${e.message}. Retrying…`)
    setTimeout(start, 2000)
    return
  }
  live(
    (msg) => {
      state = apply(state, msg)
      render()
    },
    (ok) => {
      ui.connected(ok)
      if (ok) resync()
    },
  )
  setInterval(render, 1000)
}

startSentry('kitchen')
start()
