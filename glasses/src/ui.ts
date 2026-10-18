import type { Task } from './contract'
import type { SocketStatus } from './socket'
import { taskLine } from './card'

// Phone-side companion screen. Gesture help lives here, never on the glasses display.

export interface PhoneView {
  status: SocketStatus
  screen: string
  queue: readonly Task[]
  capturing: boolean
}

let statusEl: HTMLDivElement
let queueEl: HTMLOListElement
let screenEl: HTMLSpanElement

export function mountUi(backendUrl: string): void {
  const app = document.querySelector<HTMLDivElement>('#app')!
  app.innerHTML = `
    <main class="panel">
      <header>
        <h1>Floor Sense · Server</h1>
        <div id="status" class="status status-connecting">Connecting…</div>
      </header>
      <section>
        <h2>Glasses gestures</h2>
        <ul class="help">
          <li><b>Tap</b> accept the task; tap again when it's done</li>
          <li><b>Swipe up</b> see the queue (swipe up or tap to go back)</li>
          <li><b>Swipe down</b> take an order; swipe down again to stop</li>
          <li><b>Double tap</b> exit</li>
        </ul>
      </section>
      <section>
        <h2>Queue <span id="screen" class="muted"></span></h2>
        <ol id="queue" class="queue"></ol>
      </section>
      <footer class="muted">Backend: ${backendUrl.replace(/[<>&"]/g, '')}</footer>
    </main>
  `
  statusEl = app.querySelector<HTMLDivElement>('#status')!
  queueEl = app.querySelector<HTMLOListElement>('#queue')!
  screenEl = app.querySelector<HTMLSpanElement>('#screen')!
  injectStyles()
}

export function renderPhone(view: PhoneView): void {
  if (!statusEl) return
  statusEl.className = `status status-${view.status}`
  statusEl.textContent = view.capturing ? 'Listening' : view.status
  screenEl.textContent = `(glasses: ${view.screen})`
  queueEl.replaceChildren(
    ...view.queue.map(t => {
      const li = document.createElement('li')
      const allergy = t.allergies.map(a => `! ${a.allergen} s${a.seats.join('+')}`).join(' ')
      li.textContent = `${allergy ? allergy + ' · ' : ''}${taskLine(t)} [${t.state}]`
      return li
    }),
  )
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
    h2 { font-size: 14px; margin: 0 0 8px; color: #A7A7A7; text-transform: uppercase; letter-spacing: 0.04em; }
    .help, .queue { margin: 0; padding-left: 20px; }
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
