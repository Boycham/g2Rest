// The three drawers (Paper 3OO-0): Staff, Routing log, Table details. Each slides in from the
// right over a 55% scrim (AN_08: 240ms ease-out in, 180ms ease-in out); Esc or the scrim closes.
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { gsap } from 'gsap'
import CountUp from '../components/reactbits/CountUp'
import ClickSpark from '../components/reactbits/ClickSpark'
import { store, type Task } from './backend'
import type { View } from './App'
import {
  card,
  clock,
  clock2,
  kindLabel,
  latestClip,
  rerouteTarget,
  staffName,
  staffRows,
  tableNo,
  tableTone,
} from './model.js'
import { itemsText, liveSince } from '../../../state.js'
import { TaskCard, icons, type CardView } from './ui'

const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export function Drawer({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const [mounted, setMounted] = useState(open)
  const panel = useRef<HTMLElement>(null)
  const scrim = useRef<HTMLDivElement>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const id = useId()

  useEffect(() => {
    if (open) setMounted(true)
  }, [open])

  useLayoutEffect(() => {
    if (!mounted || !panel.current || !scrim.current) return
    const fast = reduced()
    if (open) {
      gsap.fromTo(panel.current, { x: 460 }, { x: 0, duration: fast ? 0 : 0.24, ease: 'power2.out' })
      gsap.fromTo(scrim.current, { opacity: 0 }, { opacity: 1, duration: fast ? 0 : 0.24, ease: 'power1.out' })
      closeBtn.current?.focus()
    } else {
      gsap.to(panel.current, { x: 460, duration: fast ? 0 : 0.18, ease: 'power2.in' })
      gsap.to(scrim.current, { opacity: 0, duration: fast ? 0 : 0.18, ease: 'power1.in', onComplete: () => setMounted(false) })
    }
  }, [open, mounted])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!mounted) return null
  return (
    <div className="drawer-wrap" data-open={open}>
      <div className="drawer-scrim" ref={scrim} onClick={onClose} />
      <aside className="drawer" ref={panel} role="dialog" aria-modal="true" aria-labelledby={id}>
        <header className="drawer__head">
          <h2 id={id}>{title}</h2>
          <button type="button" ref={closeBtn} className="drawer__close" onClick={onClose} aria-label={`Close ${title}`}>
            {icons.close}
          </button>
        </header>
        <div className="drawer__body">{children}</div>
      </aside>
    </div>
  )
}

// ---------- Staff ----------

export function StaffDrawer({ v }: { v: View }) {
  const rows = staffRows(v.floor, v.stats, v.online)
  return (
    <ul className="staff">
      {rows.map((s: ReturnType<typeof staffRows>[number]) => (
        <li key={s.id} className="staff__row">
          <span className="avatar" data-online={s.online}>
            {s.name[0]}
          </span>
          <div className="staff__main">
            <div className="staff__name">
              {s.name}
              <span className="staff__role">
                {s.role === 'manager' ? 'Manager' : `Section ${s.sections.join(', ') || '–'}`}
              </span>
            </div>
            <div className="staff__tasks">
              {s.open.length
                ? s.open.map((o: { taskId: string; kind: string; table: string; state: string; heldSec: number }) => (
                    <span key={o.taskId} className="staff__task">
                      {kindLabel(o.kind)} · {o.table} · {o.state === 'accepted' ? `held ${clock(o.heldSec)}` : 'waiting'}
                    </span>
                  ))
                : 'No open tasks'}
            </div>
            <div className="staff__meta">
              <span data-online={s.online}>{s.online ? '● Glasses online' : '○ Glasses offline'}</span>
              {s.role === 'server' && (
                <span>
                  <CountUp to={s.done} duration={0.8} trigger="load" /> done
                  {s.avgSec != null && <> · avg {clock2(s.avgSec)}</>}
                </span>
              )}
            </div>
          </div>
        </li>
      ))}
      <li className="drawer__note">
        Times come from the backend's /stats: accept to done over this service. Slow tasks (over{' '}
        {clock2(v.stats?.doneSec ?? 300)}) alert you and move on, except food runs.
      </li>
    </ul>
  )
}

// ---------- Routing log ----------

const timeOf = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function RoutingLogDrawer({ v, onOpen }: { v: View; onOpen: (t: string) => void }) {
  const [only, setOnly] = useState('')
  const entries = v.log.filter((e: { table: string }) => !only || e.table === only)
  return (
    <>
      <label className="field drawer__filter">
        <span>Table</span>
        <select value={only} onChange={(e) => setOnly(e.target.value)}>
          <option value="">All tables</option>
          {v.floor?.tables.map((t) => (
            <option key={t.id} value={t.id}>
              {tableNo(t.id)}
            </option>
          ))}
        </select>
      </label>
      <ol className="log">
        {!entries.length && <li className="empty">No routing yet. Send a task and it shows up here.</li>}
        {entries.map((e: { seq: number; at: number; tone: string; title: string; reason: string; table: string }) => (
          <li key={e.seq} className="log__row" data-tone={e.tone}>
            <button type="button" onClick={() => onOpen(e.table)}>
              <span className="log__top">
                <span className="log__title">{e.title}</span>
                <span className="mono log__time">{timeOf(e.at)}</span>
              </span>
              <span className="log__why">{e.reason}</span>
            </button>
          </li>
        ))}
      </ol>
    </>
  )
}

// ---------- Table details ----------

const STATUSES: [string, string][] = [
  ['seated', 'Seat party'],
  ['ordered', 'Ordered'],
  ['waiting', 'Waiting on food'],
  ['eating', 'Eating'],
  ['check', 'Check'],
  ['empty', 'Clear table'],
]
const PILL: Record<string, string> = { escalated: 'ESCALATED', waiting: 'WAITING', accepted: 'ON IT', idle: 'IDLE' }

export function TableDrawer({
  v,
  table,
  onPick,
  onSendHere,
}: {
  v: View
  table: string
  onPick: (t: string) => void
  onSendHere: (t: string) => void
}) {
  const t = v.floor?.tables.find((x) => x.id === table)
  if (!t || !v.floor) return null
  const tone = tableTone(table, v.cols)
  const live = v.state.tables[table]
  const server = v.floor.sections.find((s) => s.id === t.section)?.server
  const current = tone.card as CardView | null
  const currentTask = current ? (v.state.tasks[current.id] as Task) : null
  const target = currentTask ? rerouteTarget(currentTask, v.floor, v.stats, v.online) : null
  const earlier = (Object.values(v.state.tasks) as Task[])
    .filter((x) => x.table === table && x.id !== current?.id)
    .map((x) => card(x, v.lines.get(x.id), { floor: v.floor, now: v.now, escalationSec: v.escalationSec }) as CardView)
    .reverse()
    .slice(0, 5)
  const clip = latestClip(v.state.orders, table)
  const orders = Object.values(v.state.orders).filter((o) => o.table === table && o.status !== 'cancelled')
  const over = current?.ring && current.ring.left < 0 ? -current.ring.left : null

  return (
    <div className="table-d">
      <div className="table-d__pick" role="group" aria-label="Pick a table">
        {v.floor.tables.map((x) => (
          <button key={x.id} type="button" aria-pressed={x.id === table} onClick={() => onPick(x.id)}>
            {tableNo(x.id)}
          </button>
        ))}
      </div>
      <div className="table-d__meta">
        <span className="pill" data-tone={tone.tone}>
          {PILL[tone.tone]}
        </span>
        <span>
          {t.seats} seats · section {t.section} · {staffName(v.floor, server)}
        </span>
      </div>
      <div className="stats2">
        <div className="stat">
          <span className="mono stat__n">{live && live.status !== 'empty' ? clock(liveSince(live, v.now)) : '–'}</span>
          <span className="stat__l">{live && live.status !== 'empty' ? `${cap(live.status)} for` : 'Empty table'}</span>
        </div>
        <div className="stat" data-tone={over != null ? 'red' : undefined}>
          <span className="mono stat__n">
            {over != null ? clock(over) : current?.ring ? clock(current.ring.left) : current ? '✓' : '–'}
          </span>
          <span className="stat__l">
            {over != null ? 'Over the limit' : current?.ring ? 'Left to accept' : current ? 'Accepted' : 'No open task'}
          </span>
        </div>
      </div>

      <h3 className="drawer__h">CURRENT TASK</h3>
      {current ? <TaskCard c={current} /> : <div className="empty">Nothing open at this table.</div>}

      <div className="table-d__actions">
        {currentTask && target && (
          <ClickSpark sparkColor="#e4dcc8" sparkCount={8} sparkRadius={20} style={{ width: 'auto', height: 'auto' }}>
            <button type="button" className="btn btn--bone" disabled={v.connected === false} onClick={() => store.reroute(currentTask.id, target.id)}>
              Reroute to {target.name}
            </button>
          </ClickSpark>
        )}
        <button type="button" className="btn btn--ghost" onClick={() => onSendHere(table)}>
          Send a task here
        </button>
      </div>

      {clip && (
        <>
          <h3 className="drawer__h">LATEST CLIP</h3>
          <div className="clip">
            {clip.summary && <p className="clip__summary">{clip.summary}</p>}
            {(clip.answers ?? []).map((a: { seat?: number | null; q: string; a: string; known?: boolean }, i: number) => (
              <div key={i} className="clip__qa" data-known={a.known !== false}>
                <span className="clip__q">
                  {a.known === false ? '? ' : ''}
                  {a.seat ? `Seat ${a.seat}: ` : ''}
                  {a.q}
                </span>
                <span className="clip__a">{a.known === false ? "Not on the menu data. Ask the kitchen." : a.a}</span>
              </div>
            ))}
            {(clip.uncertain ?? []).map((u: string, i: number) => (
              <div key={`u${i}`} className="clip__qa" data-known="false">
                <span className="clip__q">? {u}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {orders.length > 0 && (
        <>
          <h3 className="drawer__h">ORDERS</h3>
          {orders.map((o) => (
            <div key={o.orderId} className="order-line">
              <span className="pill" data-tone={o.status === 'draft' ? 'waiting' : 'accepted'}>
                {(o.status ?? 'draft').toUpperCase()}
              </span>
              {itemsText(o.lines.map((l) => ({ qty: l.qty, dish: `S${l.seat} ${l.dish}` }))) || 'Nothing yet'}
            </div>
          ))}
        </>
      )}

      <h3 className="drawer__h">TABLE STATUS</h3>
      <div className="status-row">
        {STATUSES.map(([status, label]) => (
          <button
            key={status}
            type="button"
            className="btn btn--ghost"
            aria-pressed={(live?.status ?? 'empty') === status}
            disabled={v.connected === false}
            onClick={() => store.tableStatus(table, status)}
          >
            {label}
          </button>
        ))}
      </div>

      {earlier.length > 0 && (
        <>
          <h3 className="drawer__h">OTHER TASKS AT THIS TABLE</h3>
          <div className="earlier">
            {earlier.map((c) => (
              <TaskCard key={c.id} c={c} />
            ))}
          </div>
        </>
      )}
      <p className="drawer__note">
        Managers can re-route or send a new task. Accept and Done happen on the glasses.
      </p>
    </div>
  )
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1)
