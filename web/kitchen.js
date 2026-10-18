// Kitchen page: live tickets by course and seat, a "food up" button per dish (stands in
// for the ESP32 button), the pass queue and the runs it created.
//
// "Food up" goes to POST /pass/up, where the backend's priority engine decides the runs.
// Until the backend has /pass, the page runs in DIRECT MODE: food up sends a RUN task
// straight to the table's section server, with no scoring or pairing, and says so on screen.
import { api, chrome, h, live } from './client.js'
import {
  allergyText,
  apply,
  emptyState,
  fmtSince,
  fromSnapshot,
  itemsText,
  seatAllergies,
  ticketRows,
} from './state.js'

const $ = (id) => document.getElementById(id)
const ui = chrome()
const RESYNC_ON = new Set(['floor.state', 'order.closed'])
const COURSE_LABEL = { appetizer: 'APP', main: 'MAIN', dessert: 'DSRT' }

let state = emptyState()
let menu = null
let floor = null
let passOn = null // null until GET /pass answers; false = direct mode
const directUp = new Set() // "orderId:line" sent in direct mode (lost on reload)

function staffName(id) {
  if (!id || !floor) return id ?? ''
  if (id === floor.manager.id) return floor.manager.name
  return floor.servers.find((s) => s.id === id)?.name ?? id
}

async function act(label, fn) {
  try {
    await fn()
  } catch (e) {
    ui.error(`${label}: ${e.message}`)
  }
}

async function loadPass() {
  try {
    state = { ...state, pass: await api('/pass') }
    passOn = true
  } catch (e) {
    if (e.status !== 404) throw e
    passOn = false
  }
}

async function resync() {
  await act('Load state', async () => {
    state = fromSnapshot(await api('/state'), state)
    if (passOn !== false) await loadPass()
    render()
  })
}

let resyncTimer
function resyncSoon() {
  clearTimeout(resyncTimer)
  resyncTimer = setTimeout(resync, 150)
}

async function foodUp(order, row) {
  await act(`Food up ${order.table} ${row.dish}`, async () => {
    if (passOn) {
      state = { ...state, pass: await api('/pass/up', { orderId: order.orderId, line: row.index }) }
    } else {
      await api('/tasks', {
        kind: 'RUN',
        table: order.table,
        items: [{ qty: row.qty, dish: row.dish, seats: [row.seat] }],
        allergies: seatAllergies(order.allergies, row.seat),
        notes: row.alterations,
      })
      directUp.add(`${order.orderId}:${row.index}`)
    }
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
    rows.map((r) => {
      const up = r.up || directUp.has(`${order.orderId}:${r.index}`)
      return h(
        'div',
        { class: `line${up ? ' up' : ''}` },
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
        draft ? null : h('button', { disabled: up, onclick: () => foodUp(order, r) }, up ? 'Up' : 'Food up'),
      )
    }),
  )
}

function renderMode() {
  const mode = $('mode')
  mode.dataset.direct = String(passOn === false)
  mode.textContent =
    passOn === false
      ? 'DIRECT MODE: the backend has no /pass yet, so "Food up" sends a RUN task straight to the section server, with no priority scoring or pairing.'
      : passOn
        ? 'Priority engine on: "Food up" puts the plate on the pass and the engine builds the runs.'
        : 'Checking the pass…'
}

function renderPass() {
  const pass = state.pass
  $('holds').replaceChildren(
    ...(pass?.holds ?? []).map((hd) =>
      h('div', { class: 'hold' }, `${hd.table} ${hd.course} held for: ${hd.waitingOn.join(', ')}`),
    ),
  )
  const plates = [...(pass?.plates ?? [])].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  $('plates').replaceChildren(
    ...(plates.length
      ? plates.map((p) =>
          h(
            'div',
            { class: 'plate' },
            h('strong', {}, `${p.table} S${p.seat} `),
            h('span', { class: p.temperature === 'hot' ? 'temp-hot' : '' }, p.dish),
            h('span', { class: 'muted' }, ` · ${p.status} · ${fmtSince(p.upSec ?? 0)}`),
            p.score != null ? h('span', { class: 'muted' }, ` · score ${Number(p.score).toFixed(1)}`) : null,
          ),
        )
      : [h('div', { class: 'empty' }, passOn ? 'Nothing at the pass.' : 'No pass queue in direct mode.')]),
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
      if (RESYNC_ON.has(msg.type)) resyncSoon()
      render()
    },
    (ok) => {
      ui.connected(ok)
      if (ok) resync()
    },
  )
  setInterval(render, 1000)
}

start()
