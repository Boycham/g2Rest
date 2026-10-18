// The dispatch bar: task kind (TAKE ORDER included), table, server (Auto-route lets the
// backend's router pick), a note, and Send Task. Paused while the backend is unreachable.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type FormEvent } from 'react'
import ClickSpark from '../components/reactbits/ClickSpark'
import { store } from './backend'
import type { View } from './App'
import { KINDS, kindLabel, tableNo } from './model.js'

export type DispatchHandle = { prefill: (table: string) => void }

const Dispatch = forwardRef<DispatchHandle, { v: View; selected: string | null }>(function Dispatch({ v, selected }, ref) {
  const [kind, setKind] = useState('RUN')
  const [table, setTable] = useState('')
  const [assignee, setAssignee] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const noteRef = useRef<HTMLInputElement>(null)
  const lost = v.connected === false

  useEffect(() => {
    if (!table && v.floor?.tables.length) setTable(selected ?? v.floor.tables[0].id)
  }, [v.floor, selected, table])

  useImperativeHandle(ref, () => ({
    prefill(t: string) {
      setTable(t)
      noteRef.current?.focus()
    },
  }))

  async function send(e: FormEvent) {
    e.preventDefault()
    if (!table || lost || busy) return
    setBusy(true)
    const text = note.trim()
    const ok = await store.dispatch({ kind, table, notes: text ? [text] : [], assignee: assignee || null })
    setBusy(false)
    if (ok) setNote('')
  }

  return (
    <form className="dispatch" onSubmit={send} aria-label="Dispatch a task" data-paused={lost}>
      <span className="dispatch__h">DISPATCH</span>
      <label className="field" style={{ width: 230 }}>
        <span>Task</span>
        <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={lost}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {kindLabel(k)}
            </option>
          ))}
        </select>
      </label>
      <label className="field" style={{ width: 150 }}>
        <span>Table</span>
        <select value={table} onChange={(e) => setTable(e.target.value)} disabled={lost}>
          {v.floor?.tables.map((t) => (
            <option key={t.id} value={t.id}>
              {tableNo(t.id)}
            </option>
          ))}
        </select>
      </label>
      <label className="field" style={{ width: 220 }}>
        <span>Server</span>
        <select value={assignee} onChange={(e) => setAssignee(e.target.value)} disabled={lost}>
          <option value="">Auto-route</option>
          {v.floor?.servers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {v.online.has(s.id) ? '' : ' (offline)'}
            </option>
          ))}
          {v.floor && <option value={v.floor.manager.id}>{v.floor.manager.name} (manager)</option>}
        </select>
      </label>
      <label className="field field--grow">
        <span className="sr-only">Note</span>
        <input
          ref={noteRef}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={lost ? 'Dispatch is paused until the backend reconnects' : 'Note: add a short message for the server'}
          maxLength={120}
          disabled={lost}
        />
      </label>
      <ClickSpark sparkColor={['#e4dcc8', '#93bf6b', '#f2efe6']} sparkCount={10} sparkRadius={26} style={{ width: 150, height: 44, flex: '0 0 auto' }}>
        <button type="submit" className="send" disabled={lost || busy || !table}>
          {busy ? 'Sending…' : 'Send Task'}
        </button>
      </ClickSpark>
    </form>
  )
})

export default Dispatch
