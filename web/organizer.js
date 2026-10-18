// Organizer page: floor plan, seat a party, dispatch a task, live dispatch board.
import { api, chrome, h, live, startSentry, traced } from './client.js'
import {
  alertText,
  allergyText,
  apply,
  boardTasks,
  emptyState,
  fmtSince,
  fromSnapshot,
  itemsText,
  liveSince,
} from './state.js'

const KINDS = ['RUN', 'CLEAR', 'CHECK', 'SEAT', 'ORDER']
const KIND_LABEL = { ORDER: 'TAKE ORDER' }
const STATUSES = [
  ['seated', 'Seat party'],
  ['ordered', 'Ordered'],
  ['waiting', 'Waiting on food'],
  ['eating', 'Eating'],
  ['check', 'Check'],
  ['empty', 'Clear table'],
]
const $ = (id) => document.getElementById(id)
const ui = chrome()

let state = emptyState()
let floor = null
let selected = null
let kind = 'RUN'

function staffName(id) {
  if (!floor) return id
  if (id === floor.manager.id) return `${floor.manager.name} (mgr)`
  return floor.servers.find((s) => s.id === id)?.name ?? id
}

function sectionServer(table) {
  return floor.sections.find((s) => s.id === table.section)?.server
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

// ---------- floor ----------

function renderFloor() {
  const w = Math.max(...floor.tables.map((t) => t.x)) + 3
  const hgt = Math.max(...floor.tables.map((t) => t.y)) + 3
  const openTasks = boardTasks(state).filter((t) => t.state === 'assigned' || t.state === 'accepted')
  $('floor').replaceChildren(
    ...floor.tables.map((t) => {
      const tl = state.tables[t.id]
      const status = tl?.status ?? 'empty'
      const open = openTasks.filter((task) => task.table === t.id).length
      return h(
        'button',
        {
          class: 'table',
          'data-status': status,
          'data-urgency': tl?.urgency ?? 0,
          'data-section': t.section,
          'aria-pressed': String(selected === t.id),
          style: {
            left: `${(t.x / w) * 100}%`,
            top: `${(t.y / hgt) * 100}%`,
            width: `${(2.6 / w) * 100}%`,
            height: `${(2.6 / hgt) * 100}%`,
          },
          onclick: () => select(t.id),
        },
        h('span', { class: 'id' }, t.id),
        open ? h('span', { class: 'badge' }, `${open} task${open > 1 ? 's' : ''}`) : null,
        h('span', { class: 'status' }, status === 'empty' ? 'empty' : `${status} · ${fmtSince(liveSince(tl))}`),
        h('span', { class: 'meta' }, `${t.seats} seats · ${staffName(sectionServer(t))}`),
      )
    }),
  )
}

// ---------- side panel ----------

function select(id) {
  selected = id
  $('dispatch').hidden = false
  render()
}

function renderAlerts() {
  const alerts = Object.values(state.alerts)
  $('alerts').replaceChildren(
    ...(alerts.length
      ? alerts.map((a) => h('div', { class: `alert ${a.level}` }, alertText(a)))
      : [h('div', { class: 'empty' }, 'Nothing needs attention.')]),
  )
}

function renderTable() {
  if (!selected) return
  const t = floor.tables.find((x) => x.id === selected)
  const tl = state.tables[selected]
  $('table-title').textContent = `${t.id} · section ${t.section} · ${t.seats} seats`
  $('table-info').replaceChildren(
    `${staffName(sectionServer(t))}'s section. `,
    tl && tl.status !== 'empty' ? `${tl.status} for ${fmtSince(liveSince(tl))}.` : 'Empty.',
  )
  $('status-row').replaceChildren(
    ...STATUSES.map(([status, label]) =>
      h(
        'button',
        {
          type: 'button',
          'aria-pressed': String(tl?.status === status),
          onclick: () => act('Table status', () => api(`/tables/${selected}/status`, { status })),
        },
        label,
      ),
    ),
  )
  const orders = Object.values(state.orders).filter((o) => o.table === selected)
  $('table-orders').replaceChildren(
    ...orders.map((o) =>
      h(
        'div',
        { class: 'muted' },
        `Order ${o.status}: `,
        itemsText(o.lines.map((l) => ({ qty: l.qty, dish: `S${l.seat} ${l.dish}` }))) || 'nothing yet',
      ),
    ),
  )
}

function buildDispatchForm() {
  const kinds = $('kinds')
  const renderKinds = () =>
    kinds.replaceChildren(
      ...KINDS.map((k) =>
        h(
          'button',
          {
            type: 'button',
            'aria-pressed': String(k === kind),
            onclick: () => {
              kind = k
              renderKinds()
            },
          },
          KIND_LABEL[k] ?? k,
        ),
      ),
    )
  renderKinds()
  $('assignee').replaceChildren(
    h('option', { value: '' }, 'Auto: section server, then escalate'),
    ...floor.servers.map((s) => h('option', { value: s.id }, s.name)),
    h('option', { value: floor.manager.id }, `${floor.manager.name} (manager)`),
  )
  $('dispatch').addEventListener('submit', (e) => {
    e.preventDefault()
    if (!selected) return
    const note = $('note').value.trim()
    act('Dispatch', async () => {
      await api('/tasks', {
        kind,
        table: selected,
        notes: note ? [note] : [],
        assignee: $('assignee').value || null,
      })
      $('note').value = ''
    })
  })
}

// ---------- board ----------

function cardText(t) {
  return [t.kind, t.table, itemsText(t.items)].filter(Boolean).join(' · ')
}

function renderBoard() {
  const tasks = boardTasks(state)
  if (!tasks.length) {
    $('board').replaceChildren(h('div', { class: 'empty' }, 'No tasks yet. Pick a table and dispatch one.'))
    return
  }
  const now = Date.now()
  $('board').replaceChildren(
    h(
      'table',
      { class: 'tasks' },
      h(
        'tr',
        {},
        ['Card', 'Assigned to', 'State', 'Age'].map((c) => h('th', {}, c)),
      ),
      tasks.map((t) => {
        const allergies = allergyText(t.allergies ?? [])
        const age = t.createdAt ? fmtSince(Math.max(0, Math.floor((now - Date.parse(t.createdAt)) / 1000))) : ''
        return h(
          'tr',
          { class: t.state },
          h(
            'td',
            { class: 'card' },
            allergies ? h('div', { class: 'allergy' }, allergies) : null,
            h('div', {}, cardText(t)),
            (t.notes ?? []).map((n) => h('div', { class: 'muted' }, n)),
          ),
          h('td', {}, staffName(t.assignee)),
          h(
            'td',
            {},
            h('span', { class: `pill ${t.state}` }, t.state),
            t.backendState && t.backendState !== t.state ? h('span', { class: 'muted' }, ` ${t.backendState}`) : null,
          ),
          h('td', { class: 'muted' }, age),
        )
      }),
    ),
  )
}

function render() {
  if (!floor) return
  renderFloor()
  renderAlerts()
  renderTable()
  renderBoard()
}

// ---------- start ----------

$('reset').addEventListener('click', () => {
  if (!confirm('Reset the whole service? Every task, order and table status is cleared.')) return
  act('Reset', async () => {
    await api('/reset', {})
    await resync()
  })
})

async function start() {
  try {
    floor = await api('/floor')
  } catch (e) {
    ui.error(`Could not load the floor plan: ${e.message}. Retrying…`)
    setTimeout(start, 2000)
    return
  }
  buildDispatchForm()
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

startSentry('organizer')
start()
