// ALERTS: every alert the backend raises, whatever its kind (unaccepted, slow, 86, VIP, ...),
// drawn from its payload: level picks the colour, text is shown as sent, `table` links to the
// table. Alerts about a task get a Reroute button. Diner questions the menu couldn't answer
// ("?" lines from clip summaries) sit in the same rail. Dismiss hides an item on this screen.
import { useMemo, useState } from 'react'
import ClickSpark from '../components/reactbits/ClickSpark'
import { store, type Alert } from './backend'
import type { View } from './App'
import { alertTask, card, clock, rerouteTarget, tableNo } from './model.js'
import { alertText, liveSince } from '../../../state.js'

const LEVEL_RANK: Record<string, number> = { urgent: 0, warn: 1, info: 2 }
const DISMISSED_KEY = 'verity-dismissed'

function loadDismissed(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(DISMISSED_KEY) ?? '[]'))
  } catch {
    return new Set()
  }
}

export default function AlertsRail({ v, onOpen }: { v: View; onOpen: (t: string) => void }) {
  const [dismissed, setDismissed] = useState(loadDismissed)
  const dismiss = (key: string) => {
    const next = new Set(dismissed).add(key)
    setDismissed(next)
    try {
      sessionStorage.setItem(DISMISSED_KEY, JSON.stringify([...next].slice(-200)))
    } catch {
      /* private mode: dismiss for this page view only */
    }
  }

  const alerts = useMemo(
    () =>
      (Object.values(v.state.alerts) as Alert[])
        .filter((a) => !dismissed.has(`${a.id}|${a.text}`))
        .sort((a, b) => (LEVEL_RANK[a.level] ?? 3) - (LEVEL_RANK[b.level] ?? 3) || b.sinceSec - a.sinceSec),
    [v.state.alerts, dismissed],
  )
  const questions = v.questions.filter((q: { orderId: string; q: string }) => !dismissed.has(`q|${q.orderId}|${q.q}`))
  const count = alerts.length + questions.length

  return (
    <section className="panel alerts" aria-labelledby="alerts-h">
      <div className="panel__row">
        <h2 id="alerts-h" className="panel__h">
          ALERTS
        </h2>
        <span className="count" data-tone={count ? 'red' : 'stone'} aria-label={`${count} alerts`}>
          {count}
        </span>
      </div>
      <div className="alerts__list">
        {!count && <div className="empty">Nothing needs you right now.</div>}
        {alerts.map((a) => {
          const taskId = alertTask(a, v.links, v.state.tasks)
          const task = taskId ? v.state.tasks[taskId] : null
          const open = task && task.state !== 'done'
          const view = open ? card(task, v.lines.get(task.id), { floor: v.floor, now: v.now, escalationSec: v.escalationSec, alerted: true }) : null
          const target = open ? rerouteTarget(task, v.floor, v.stats, v.online) : null
          return (
            <article key={a.id} className="alert" data-level={a.level}>
              <div className="alert__top">
                <h3>
                  {a.table ? `Table ${tableNo(a.table)} · ` : ''}
                  {view ? `${view.title} ${a.id.startsWith('slow-') ? 'running long' : 'escalated'}` : alertText(a, v.now)}
                </h3>
                <span className="mono alert__time">{clock(liveSince(a, v.now))}</span>
              </div>
              {view && <p>{`${alertText(a, v.now)}. ${view.subtitle}.`}</p>}
              <div className="alert__actions">
                {open && target && (
                  <ClickSpark sparkColor="#e4dcc8" sparkCount={8} sparkRadius={20} style={{ width: 'auto', height: 'auto' }}>
                    <button type="button" className="btn btn--bone" disabled={v.connected === false} onClick={() => store.reroute(task.id, target.id)}>
                      Reroute to {target.name}
                    </button>
                  </ClickSpark>
                )}
                {a.table && (
                  <button type="button" className="btn btn--ghost" onClick={() => onOpen(a.table!)}>
                    Open table
                  </button>
                )}
                <button type="button" className="btn btn--ghost" onClick={() => dismiss(`${a.id}|${a.text}`)}>
                  Dismiss
                </button>
              </div>
            </article>
          )
        })}
        {questions.map((q: { table: string; orderId: string; seat: number | null; q: string }) => (
          <article key={`${q.orderId}|${q.q}`} className="alert" data-level="question">
            <div className="alert__top">
              <h3>
                <span className="q-mark">?</span> Table {tableNo(q.table)}
                {q.seat ? ` · seat ${q.seat}` : ''} asked
              </h3>
            </div>
            <p>“{q.q}” The menu can't answer this one, so check with the kitchen.</p>
            <div className="alert__actions">
              <button type="button" className="btn btn--ghost" onClick={() => onOpen(q.table)}>
                Open table
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => dismiss(`q|${q.orderId}|${q.q}`)}>
                Dismiss
              </button>
            </div>
          </article>
        ))}
      </div>
      <span className="sr-only" aria-live="polite">
        {count ? `${count} alerts` : ''}
      </span>
    </section>
  )
}
