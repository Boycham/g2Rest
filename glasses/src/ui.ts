import type { Task } from './contract'
import type { SocketStatus } from './socket'
import { taskLine } from './card'
import { ROLES, type Role } from './hud'
import { GLYPH_LEGEND } from './minimap'

// Phone-side companion screen: the role picker, and gesture help (never on the glasses).

export interface PhoneView {
  role: Role
  status: SocketStatus
  screen: string
  queue: readonly Task[]
  /** The mic is keeping the last minute (in WebView memory only). */
  recording: boolean
  bufferedSeconds: number
  alerts: readonly string[]
  tables: readonly string[]
}

let statusEl: HTMLDivElement
let queueEl: HTMLOListElement
let roleEl: HTMLSelectElement
let alertsEl: HTMLOListElement
let tablesEl: HTMLOListElement
let sections: Record<Role, HTMLElement[]>

const esc = (s: string) => s.replace(/[<>&"]/g, '')

export function mountUi(backendUrl: string, onRole: (role: Role) => void): void {
  const app = document.querySelector<HTMLDivElement>('#app')!
  app.innerHTML = `
    <main class="panel">
      <header>
        <h1>Floor Sense ·
          <select id="role" aria-label="Role">
            ${ROLES.map(r => `<option value="${r}">${r[0]!.toUpperCase()}${r.slice(1)}</option>`).join('')}
          </select>
        </h1>
        <div id="status" class="status status-connecting">Connecting…</div>
      </header>
      <section data-role="server">
        <h2>Glasses gestures</h2>
        <ul class="help">
          <li><b>Tap</b> accept the task; tap again when it's done</li>
          <li><b>Swipe forward</b> (toward your eyes) Controls: every gesture, its "verity" command, and the queue</li>
          <li><b>Swipe back</b> (toward your ear) send the last minute: the order shows as a draft (tap = send)</li>
          <li><b>Hold</b> hand the task off (tap to confirm)</li>
          <li><b>Double tap</b> exit</li>
        </ul>
      </section>
      <section data-role="server">
        <p class="muted">While the Server role is on, the glasses mic keeps only the last 60 s, in this app's memory.
          Older audio is dropped as it goes. Only a swipe back sends that minute to the backend, which
          transcribes it, keeps the order and discards the audio.</p>
      </section>
      <section data-role="server">
        <h2>Queue <span class="muted screen"></span></h2>
        <ol id="queue" class="queue"></ol>
      </section>
      <section data-role="manager" hidden>
        <h2>Glasses gestures</h2>
        <ul class="help">
          <li><b>Tap</b> dismiss the top exception (on this device only)</li>
          <li><b>Swipe back</b> floor minimap (swipe forward or tap to go back)</li>
          <li><b>Double tap</b> exit</li>
        </ul>
        <p class="muted">Minimap: brightest box needs you. ${GLYPH_LEGEND.map(([g, m]) => `<b>${g}</b> ${m}`).join(' · ')}</p>
      </section>
      <section data-role="manager" hidden>
        <h2>Exceptions <span class="muted screen"></span></h2>
        <ol id="alerts" class="queue"></ol>
        <h2>Floor</h2>
        <ol id="tables" class="queue"></ol>
      </section>
      <footer class="muted">Backend: ${esc(backendUrl)}</footer>
    </main>
  `
  statusEl = app.querySelector<HTMLDivElement>('#status')!
  queueEl = app.querySelector<HTMLOListElement>('#queue')!
  alertsEl = app.querySelector<HTMLOListElement>('#alerts')!
  tablesEl = app.querySelector<HTMLOListElement>('#tables')!
  roleEl = app.querySelector<HTMLSelectElement>('#role')!
  const all = [...app.querySelectorAll<HTMLElement>('section[data-role]')]
  sections = { server: all.filter(s => s.dataset.role === 'server'), manager: all.filter(s => s.dataset.role === 'manager') }
  roleEl.addEventListener('change', () => onRole(roleEl.value as Role))
  injectStyles()
}

function items(list: readonly string[], empty: string): HTMLLIElement[] {
  return (list.length ? list : [empty]).map(text => {
    const li = document.createElement('li')
    li.textContent = text
    if (!list.length) li.className = 'muted'
    return li
  })
}

export function renderPhone(view: PhoneView): void {
  if (!statusEl) return
  roleEl.value = view.role
  for (const role of ROLES) for (const s of sections[role]) s.hidden = role !== view.role
  statusEl.className = `status status-${view.status}`
  statusEl.textContent =
    view.role === 'server'
      ? `${view.status} · ${view.recording ? `mic: last ${Math.round(view.bufferedSeconds)} s in memory` : 'mic off'}`
      : view.status
  for (const el of document.querySelectorAll<HTMLSpanElement>('.screen')) el.textContent = `(glasses: ${view.screen})`
  queueEl.replaceChildren(
    ...view.queue.map(t => {
      const li = document.createElement('li')
      const allergy = t.allergies.map(a => `! ${a.allergen} s${a.seats.join('+')}`).join(' ')
      li.textContent = `${allergy ? allergy + ' · ' : ''}${taskLine(t)} [${t.state}]`
      return li
    }),
  )
  alertsEl.replaceChildren(...items(view.alerts, 'No exceptions'))
  tablesEl.replaceChildren(...items(view.tables, 'No floor data yet'))
}

function injectStyles(): void {
  const css = `
    :root { color-scheme: dark; }
    html, body { margin: 0; height: 100%; background: #232323; color: #E5E5E5;
      font: 16px/1.4 -apple-system, BlinkMacSystemFont, 'Helvetica Neue', system-ui, sans-serif;
      touch-action: manipulation; -webkit-text-size-adjust: 100%; overscroll-behavior: none; }
    .panel { display: flex; flex-direction: column; gap: 16px; max-width: 640px; margin: 0 auto;
      padding: 24px; box-sizing: border-box; }
    header { display: flex; align-items: center; justify-content: space-between; }
    h1 { font-size: 18px; font-weight: 600; margin: 0; }
    h1 select { font: inherit; background: #2E2E2E; color: inherit; border: 1px solid #3E3E3E; border-radius: 6px; padding: 2px 6px; }
    h2 { font-size: 14px; margin: 0 0 8px; color: #A7A7A7; text-transform: uppercase; letter-spacing: 0.04em; }
    .help, .queue { margin: 0 0 12px; padding-left: 20px; }
    .muted { color: #7B7B7B; font-size: 12px; }
    .status { font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid #3E3E3E;
      text-transform: uppercase; letter-spacing: 0.04em; }
    .status-online { color: #3CFA44; border-color: #3CFA44; }
    .status-offline { color: #FF453A; border-color: #FF453A; }
    .status-connecting { color: #A7A7A7; }
  `
  const style = document.createElement('style')
  style.textContent = css
  document.head.appendChild(style)
}
