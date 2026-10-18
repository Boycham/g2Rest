// FLOOR · LIVE: the room from above, one tile per table. A tile's ring is its most urgent
// open task (idle, waiting, accepted, escalated; dashed after a bounce); the badge is who
// holds that task; "?" marks a diner question the menu couldn't answer.
import { useEffect, useState } from 'react'
import { store } from './backend'
import type { View } from './App'
import { clock, staffName, tableNo, tableSpots, tableTone } from './model.js'
import { fmtSince, liveSince } from '../../../state.js'

const STROKE: Record<string, string> = { idle: '#C2BCAE', waiting: '#E4DCC8', accepted: '#93BF6B', escalated: '#E4543E' }
const TONE_WORD: Record<string, string> = {
  idle: 'no open tasks',
  waiting: 'task waiting for accept',
  accepted: 'task accepted',
  escalated: 'task escalated',
}

function Chairs({ seats }: { seats: number }) {
  const wood = '#4B2F1C'
  const side = (
    <>
      <rect x="4" y="38" width="15" height="34" rx="6" fill={wood} />
      <rect x="111" y="38" width="15" height="34" rx="6" fill={wood} />
    </>
  )
  if (seats <= 2) return side
  if (seats <= 4)
    return (
      <>
        <rect x="35" y="4" width="60" height="15" rx="6" fill={wood} />
        <rect x="35" y="91" width="60" height="15" rx="6" fill={wood} />
        {side}
      </>
    )
  return (
    <>
      <rect x="22" y="4" width="38" height="15" rx="6" fill={wood} />
      <rect x="70" y="4" width="38" height="15" rx="6" fill={wood} />
      <rect x="22" y="91" width="38" height="15" rx="6" fill={wood} />
      <rect x="70" y="91" width="38" height="15" rx="6" fill={wood} />
      {side}
    </>
  )
}

function LostBanner({ retryAt }: { retryAt: number | null }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [])
  const wait = retryAt ? Math.max(0, Math.ceil((retryAt - now) / 1000)) : 0
  return (
    <div className="lost" role="alert">
      <div className="lost__title">Backend disconnected</div>
      <p>
        Showing the last known floor state. Tasks already on glasses keep working. New tasks cannot be sent until the
        connection returns.
      </p>
      <div className="lost__row">
        <button type="button" className="btn btn--bone" onClick={() => store.retry()}>
          Retry now
        </button>
        <span className="mono">{wait ? `Retrying in ${clock(wait)}` : 'Retrying…'}</span>
      </div>
    </div>
  )
}

export default function FloorMap({ v, selected, onOpen }: { v: View; selected: string | null; onOpen: (t: string) => void }) {
  const spots = tableSpots(v.floor)
  const asked = new Set(v.questions.map((q: { table: string }) => q.table))
  return (
    <section className="panel floor" aria-labelledby="floor-h">
      <div className="floor__head">
        <h2 id="floor-h" className="panel__h">
          FLOOR · LIVE
        </h2>
        <ul className="legend" aria-label="Legend">
          {['idle', 'waiting', 'accepted', 'escalated'].map((t) => (
            <li key={t}>
              <span style={{ background: STROKE[t] }} />
              {t[0].toUpperCase() + t.slice(1)}
            </li>
          ))}
        </ul>
      </div>
      <div className="map">
        <img className="map__img" src={`${import.meta.env.BASE_URL}assets/floor.jpg`} alt="" />
        <div className="map__pass">KITCHEN PASS</div>
        <div className="map__door">ENTRANCE</div>
        {spots.map((t) => {
          const tone = tableTone(t.id, v.cols)
          const live = v.state.tables[t.id]
          const status = live && live.status !== 'empty' ? `${live.status} ${fmtSince(liveSince(live, v.now))}` : ''
          const server = v.floor?.sections.find((s) => s.id === t.section)?.server
          const holder = tone.card?.assignee
          return (
            <button
              key={t.id}
              type="button"
              className="tile"
              data-tone={tone.tone}
              aria-pressed={selected === t.id}
              style={{ left: `${t.fx * 100}%`, top: `${t.fy * 100}%` }}
              onClick={() => onOpen(t.id)}
              aria-label={`Table ${tableNo(t.id)}, ${t.seats} seats, ${staffName(v.floor, server)}'s section, ${TONE_WORD[tone.tone]}${status ? `, ${status}` : ''}`}
            >
              <svg viewBox="0 0 130 110" aria-hidden="true">
                <Chairs seats={t.seats} />
                {tone.tone === 'escalated' && (
                  <rect className="tile__halo" x="19" y="19" width="92" height="72" rx="16" fill="none" stroke="#E4543E" strokeWidth="3" />
                )}
                <rect
                  x="25"
                  y="25"
                  width="80"
                  height="60"
                  rx="12"
                  fill="#D6CBB4"
                  stroke={STROKE[tone.tone]}
                  strokeWidth="5"
                  strokeDasharray={tone.dashed ? '7 6' : undefined}
                />
              </svg>
              <span className="tile__no">{tableNo(t.id)}</span>
              {status && <span className="tile__status">{status}</span>}
              {holder && (
                <span className="tile__badge" data-tone={tone.tone} title={staffName(v.floor, holder)}>
                  {staffName(v.floor, holder)[0]}
                </span>
              )}
              {asked.has(t.id) && (
                <span className="tile__ask" title="A diner asked something the menu can't answer">
                  ?
                </span>
              )}
            </button>
          )
        })}
        {v.connected === false && <LostBanner retryAt={v.retryAt} />}
      </div>
    </section>
  )
}
