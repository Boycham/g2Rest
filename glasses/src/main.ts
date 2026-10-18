import { CreateStartUpPageContainer, OsEventTypeList, waitForEvenAppBridge, type EvenHubEvent } from '@evenrealities/even_hub_sdk'
import { backendUrl, redactToken } from './backend-url'
import { alertRows } from './exceptions'
import type { Hud, HudContext, Role } from './hud'
import { ManagerHud } from './manager'
import { loadDone } from './reconcile'
import { tableRows } from './minimap'
import { ServerHud } from './server'
import { BackendSocket, type SocketStatus } from './socket'
import { loadManager, loadQueue, loadRole, saveRole } from './storage'
import { log } from './log'
import { mountUi, renderPhone } from './ui'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'ws://localhost:8787/ws'
// Dev token only: it ships in the WebView bundle (glasses/NOTES.md).
const urlFor = (r: Role) => backendUrl(BACKEND_URL, r, import.meta.env.VITE_FS_TOKEN, import.meta.env.VITE_FS_STAFF)

let status: SocketStatus = 'connecting'

mountUi(redactToken(BACKEND_URL), next => void switchRole(next))
const bridge = await waitForEvenAppBridge()
let role: Role = await loadRole(bridge)
const restoredQueue = await loadQueue(bridge)
const restoredManager = await loadManager(bridge)
const restoredDone = await loadDone(bridge)
log('role', role, 'restored queue', restoredQueue.length, 'alerts', restoredManager.exceptions.open.length)

const socket = new BackendSocket(urlFor(role), {
  onMessage: msg => {
    server.onMessage(msg)
    manager.onMessage(msg)
  },
  onStatus: s => {
    status = s
    log('status', s)
    server.onStatus()
    manager.onStatus()
    syncPhone()
  },
})

const context = (r: Role): HudContext => ({
  bridge,
  socket,
  status: () => status,
  active: () => role === r,
  syncPhone,
})
const server = new ServerHud(context('server'), restoredQueue, restoredDone)
const manager = new ManagerHud(context('manager'), restoredManager)
const active = (): Hud => (role === 'server' ? server : manager)

function syncPhone(): void {
  const now = Date.now()
  renderPhone({
    role,
    status,
    screen: active().screen(),
    queue: server.queue,
    recording: role === 'server' && server.recording,
    bufferedSeconds: server.bufferedSeconds,
    alerts: alertRows(manager.exceptions, now),
    tables: tableRows(manager.tables, now),
  })
}

const created = await bridge.createStartUpPageContainer(new CreateStartUpPageContainer(active().startPage()))
log('createStartUpPageContainer', role, created)
if (role === 'server') void server.startRecording()

async function switchRole(next: Role): Promise<void> {
  if (next === role) return
  active().leave()
  role = next
  log('role ->', role)
  await saveRole(bridge, role)
  // The backend routes by the role/staff on the socket, so a new role is a new connection.
  socket.redial(urlFor(role))
  await active().enter()
  syncPhone()
}

// ---------- gestures and lifecycle ----------

// CLICK_EVENT is 0 and protobuf omits zero values, so a tap arrives as an envelope whose
// eventType is undefined. Resolve that default only inside an envelope that exists, or
// every audio frame would read as a tap.
function eventTypeOf(event: EvenHubEvent): OsEventTypeList | null {
  const envelope = event.sysEvent ?? event.textEvent ?? event.listEvent
  if (!envelope) return null
  return envelope.eventType ?? OsEventTypeList.CLICK_EVENT
}

let cleanedUp = false
function cleanup(): void {
  if (cleanedUp) return
  cleanedUp = true
  server.cleanup()
  manager.cleanup()
}

bridge.onEvenHubEvent(event => {
  if (event.audioEvent) return server.onAudio(event.audioEvent.audioPcm)
  const type = eventTypeOf(event)
  if (type === null) return
  const hud = active()
  const where = `${hud.role}/${hud.screen()}`
  switch (type) {
    case OsEventTypeList.DOUBLE_CLICK_EVENT:
      // Even Hub review rule: double tap exits through the system dialog, nothing else.
      log('double tap -> shutDownPageContainer(1)')
      void bridge.shutDownPageContainer(1)
      return
    case OsEventTypeList.CLICK_EVENT:
      log('tap on', where)
      return hud.onTap()
    case OsEventTypeList.SCROLL_TOP_EVENT:
      log('swipe up on', where)
      return hud.onSwipeUp()
    case OsEventTypeList.SCROLL_BOTTOM_EVENT:
      log('swipe down on', where)
      return hud.onSwipeDown()
    case OsEventTypeList.FOREGROUND_ENTER_EVENT:
      log('foreground enter: reconnecting')
      socket.reconnectNow()
      return
    case OsEventTypeList.FOREGROUND_EXIT_EVENT:
      // The mic is left on: whether it keeps running in the background is HW-PENDING.
      log('foreground exit: saving state')
      server.save()
      manager.save()
      return
    case OsEventTypeList.SYSTEM_EXIT_EVENT:
    case OsEventTypeList.ABNORMAL_EXIT_EVENT:
      log('exit event', type)
      cleanup()
      return
    default:
      return
  }
})

window.addEventListener('beforeunload', cleanup)
socket.connect()
syncPhone()
