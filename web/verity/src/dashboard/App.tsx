// The manager dashboard (Paper page 08): header, dispatch bar, live floor map, alerts rail,
// drawer launcher, and the four-column task board, with the Staff, Routing log and Table
// details drawers over it. Managers send and re-route; accept and done stay on the glasses.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useBackend, useNow } from './backend'
import { alertTask, alertTasks, board, openQuestions, routingLog, timelines } from './model.js'
import Header from './Header'
import Dispatch, { type DispatchHandle } from './Dispatch'
import FloorMap from './FloorMap'
import AlertsRail from './AlertsRail'
import Board from './Board'
import { Drawer, RoutingLogDrawer, StaffDrawer, TableDrawer } from './Drawers'
import { icons } from './ui'

export type DrawerKind = 'staff' | 'log' | 'table' | null

export function useView() {
  const b = useBackend()
  const now = useNow(1000)
  const escalationSec = b.stats?.escalationSec ?? 30
  const view = useMemo(() => {
    const lines = timelines(b.events)
    const links = alertTasks(b.events)
    const alertedTasks = new Set(
      Object.values(b.state.alerts)
        .map((a) => alertTask(a, links, b.state.tasks))
        .filter(Boolean),
    )
    const cols = board(b.state.tasks, lines, { floor: b.floor, now, escalationSec, alertedTasks })
    return {
      lines,
      links,
      cols,
      log: routingLog(b.events, b.floor),
      questions: openQuestions(b.state.orders),
    }
  }, [b.events, b.state, b.floor, now, escalationSec])
  return { ...b, ...view, now, escalationSec }
}
export type View = ReturnType<typeof useView>

export default function App() {
  const v = useView()
  const [drawer, setDrawer] = useState<DrawerKind>(null)
  const [table, setTable] = useState<string | null>(null)
  const dispatch = useRef<DispatchHandle>(null)
  const returnFocus = useRef<HTMLElement | null>(null)

  const open = useCallback((kind: DrawerKind, t?: string) => {
    returnFocus.current = document.activeElement as HTMLElement | null
    if (t) setTable(t)
    setDrawer(kind)
  }, [])
  const openTable = useCallback((t: string) => open('table', t), [open])
  const close = useCallback(() => {
    setDrawer(null)
    returnFocus.current?.focus?.()
  }, [])

  useEffect(() => {
    if (!table && v.floor) setTable(v.floor.tables[0]?.id ?? null)
  }, [v.floor, table])

  const sendHere = useCallback(
    (t: string) => {
      close()
      dispatch.current?.prefill(t)
    },
    [close],
  )

  return (
    <div className="dash" data-lost={v.connected === false}>
      <Header v={v} drawer={drawer} onOpen={open} />
      <Dispatch ref={dispatch} v={v} selected={table} />
      <FloorMap v={v} selected={drawer === 'table' ? table : null} onOpen={openTable} />
      <div className="side">
        <AlertsRail v={v} onOpen={openTable} />
        <section className="panel launcher" aria-labelledby="launcher-h">
          <h2 id="launcher-h" className="panel__h">
            OPEN A DRAWER
          </h2>
          <div className="launcher__row">
            <button type="button" className="launch" onClick={() => open('staff')}>
              {icons.staff}
              Staff
            </button>
            <button type="button" className="launch" onClick={() => open('log')}>
              {icons.log}
              Routing log
            </button>
            <button type="button" className="launch" onClick={() => open('table')}>
              {icons.table}
              Table details
            </button>
          </div>
        </section>
      </div>
      <Board v={v} onOpen={openTable} />

      <Drawer open={drawer === 'staff'} title="Staff" onClose={close}>
        <StaffDrawer v={v} />
      </Drawer>
      <Drawer open={drawer === 'log'} title="Routing log" onClose={close}>
        <RoutingLogDrawer v={v} onOpen={openTable} />
      </Drawer>
      <Drawer open={drawer === 'table'} title={table ? `Table ${table.replace(/\D/g, '').padStart(2, '0')}` : 'Table'} onClose={close}>
        {table && <TableDrawer v={v} table={table} onPick={setTable} onSendHere={sendHere} />}
      </Drawer>

      {v.toast && (
        <div className="toast" role="alert">
          {v.toast}
        </div>
      )}
      <div className="narrow" role="note">
        <img src={`${import.meta.env.BASE_URL}assets/logo-cream.png`} alt="Verity" width={110} height={48} />
        <p>The manager dashboard needs a screen at least 1024 pixels wide, like a tablet in landscape or a laptop.</p>
      </div>
    </div>
  )
}
