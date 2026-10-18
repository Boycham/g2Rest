import { links } from '../shared/links'
import type { DrawerKind, View } from './App'
import { hms, shiftLeft } from './model.js'
import { StatusChip } from './ui'

// The shift end isn't a backend setting yet: ?shiftEnd=HH:MM, else the next service end
// (lunch 15:00, dinner 22:00; see SERVICE_ENDS in model.js).
const SHIFT_END = new URLSearchParams(location.search).get('shiftEnd') ?? undefined

const TABS: { label: string; drawer: DrawerKind }[] = [
  { label: 'Floor', drawer: null },
  { label: 'Staff', drawer: 'staff' },
  { label: 'Routing logs', drawer: 'log' },
  { label: 'Tables', drawer: 'table' },
]

export default function Header({ v, drawer, onOpen }: { v: View; drawer: DrawerKind; onOpen: (d: DrawerKind) => void }) {
  const glasses = v.floor ? [...v.floor.servers.map((s) => s.id), v.floor.manager.id] : []
  const on = glasses.filter((id) => v.online.has(id)).length
  const left = shiftLeft(v.now, SHIFT_END)
  const backend = v.connected === false ? 'red' : v.connected ? 'leaf' : 'bone'
  return (
    <header className="head">
      <div className="head__brand">
        <a href={links.story} aria-label="Verity story page">
          <img src={`${import.meta.env.BASE_URL}assets/logo-cream.png`} alt="Verity" width={96} height={42} />
        </a>
        <span className="head__rule" />
        <div>
          <div className="head__name">{v.floor?.restaurant ?? 'Loading…'}</div>
          <div className="head__sub">Main floor</div>
        </div>
      </div>
      <div className="head__shift">
        <span>SHIFT ENDS IN</span>
        <span className="mono head__clock">{hms(left)}</span>
      </div>
      <div className="head__chips">
        <StatusChip tone={backend}>
          {v.connected === false ? 'Backend disconnected' : v.connected ? 'Backend connected' : 'Connecting…'}
        </StatusChip>
        <StatusChip tone={on === glasses.length && on > 0 ? 'leaf' : on ? 'bone' : 'red'}>
          Glasses {on}/{glasses.length} online
        </StatusChip>
      </div>
      <nav className="tabs" aria-label="Views">
        {TABS.map((t) => (
          <button
            key={t.label}
            type="button"
            className="tab"
            aria-current={drawer === t.drawer ? 'page' : undefined}
            onClick={() => onOpen(t.drawer)}
          >
            {t.label}
          </button>
        ))}
        <a className="tab" href={links.kitchen}>
          Kitchen ↗
        </a>
      </nav>
    </header>
  )
}
