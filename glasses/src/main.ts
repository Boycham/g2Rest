import { CreateStartUpPageContainer, OsEventTypeList, waitForEvenAppBridge, type EvenHubEvent } from '@evenrealities/even_hub_sdk'
import { backendUrl, redactToken } from './backend-url'
import { alertRows } from './exceptions'
import type { Hud, HudContext, Role } from './hud'
import { ManagerHud } from './manager'
import { loadDone } from './reconcile'
import { tableRows } from './minimap'
import { ServerHud } from './server'
import { BackendSocket, type SocketStatus } from './socket'
import { loadManager, loadQueue, loadRamp, loadRole, saveRole } from './storage'
import { log } from './log'
import { mountUi, renderPhone } from './ui'
import { MAIN_ID } from './render'
import * as telemetry from './telemetry'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'ws://localhost:8787/ws'
// Dev token only: it ships in the WebView bundle (glasses/NOTES.md).
const urlFor = (r: Role) => backendUrl(BACKEND_URL, r, import.meta.env.VITE_FS_TOKEN, import.meta.env.VITE_FS_STAFF)
const staffOf = (r: Role) => new URL(urlFor(r)).searchParams.get('staff') ?? ''
const FS_TOKEN = import.meta.env.VITE_FS_TOKEN || new URL(BACKEND_URL).searchParams.get('token') || ''

let status: SocketStatus = 'connecting'

mountUi(redactToken(BACKEND_URL), next => void switchRole(next))
const bridge = await waitForEvenAppBridge()
let role: Role = await loadRole(bridge)
const restoredQueue = await loadQueue(bridge)
const restoredManager = await loadManager(bridge)
const restoredDone = await loadDone(bridge)
const restoredRamp = await loadRamp(bridge)
// Sentry starts on its own once GET /config answers; the app never waits for it.
void telemetry.startTelemetry({ wsUrl: BACKEND_URL, token: FS_TOKEN, tags: { role, staff: staffOf(role) } })
telemetry.watchLens(bridge, MAIN_ID)
log('role', role, 'restored queue', restoredQueue.length, 'alerts', restoredManager.exceptions.open.length)

const socket = new BackendSocket(() => urlFor(role), {
  onMessage: msg => {
    if (msg.type !== 'floor.state') telemetry.crumb('frame.in', msg.type, telemetry.frameData(msg))
    if (msg.type === 'voice.command') telemetry.noteInput(`verity ${msg.intent}`)
    if (msg.type === 'task.assigned') telemetry.taskAssigned(msg)
    server.onMessage(msg)
    manager.onMessage(msg)
    if (msg.type === 'task.assigned' && !(role === 'server' && server.screen() === 'card'))
      telemetry.cardNotShown(server.queue[0]?.id === msg.task.id)
  },
  onSent: msg => telemetry.crumb('frame.out', msg.type, telemetry.frameData(msg)),
  onClose: code => telemetry.crumb('socket', 'closed', { code }),
  onStatus: s => {
    status = s
    log('status', s)
    telemetry.crumb('socket', s)
    telemetry.logInfo(`socket ${s}`, { role })
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
const server = new ServerHud(context('server'), restoredQueue, restoredDone, { staff: staffOf('server'), prefs: restoredRamp })
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
  telemetry.crumb('role', role)
  telemetry.setTags({ role, staff: staffOf(role) })
  await saveRole(bridge, role)
  // The backend routes by the role/staff on the socket, so a new role is a new connection.
  socket.reconnectNow()
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

// OS input -> gesture, in one place (what each gesture does on the card: MAIN_GESTURES in
// controls.ts). Double tap must stay exit on the root page or Even Hub review rejects the app.
const GESTURE_EVENTS: Partial<Record<OsEventTypeList, 'tap' | 'up' | 'down' | 'hold' | 'exit'>> = {
  [OsEventTypeList.CLICK_EVENT]: 'tap',
  [OsEventTypeList.SCROLL_TOP_EVENT]: 'up',
  [OsEventTypeList.SCROLL_BOTTOM_EVENT]: 'down',
  [OsEventTypeList.LONG_PRESS_EVENT]: 'hold',
  [OsEventTypeList.DOUBLE_CLICK_EVENT]: 'exit',
}

/** What people read (breadcrumbs, span attributes): swipe fwd/back, never up/down. */
const GESTURE_NAMES = { tap: 'tap', up: 'swipe fwd', down: 'swipe back', hold: 'long press', exit: 'double tap' } as const

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
  const gesture = GESTURE_EVENTS[type]
  if (gesture) {
    log(gesture, 'on', where)
    telemetry.noteInput(GESTURE_NAMES[gesture])
    telemetry.crumb('gesture', GESTURE_NAMES[gesture], { where })
    if (gesture === 'exit') {
      // Even Hub review rule: double tap exits through the system dialog, nothing else.
      void bridge.shutDownPageContainer(1)
      return
    }
    if (gesture === 'tap') return hud.onTap()
    if (gesture === 'up') return hud.onSwipeUp()
    if (gesture === 'down') return hud.onSwipeDown()
    return hud.onLongPress()
  }
  switch (type) {
    case OsEventTypeList.IMU_DATA_REPORT:
      if (event.sysEvent?.imuData) server.onImu(event.sysEvent.imuData)
      return
    case OsEventTypeList.FOREGROUND_ENTER_EVENT:
      log('foreground enter: reconnecting')
      telemetry.crumb('socket', 'reconnect (foreground)')
      socket.reconnectNow()
      return
    case OsEventTypeList.FOREGROUND_EXIT_EVENT:
      // The mic is left on: whether it keeps running in the background is HW-PENDING.
      log('foreground exit: saving state')
      server.save()
      manager.save()
      telemetry.crumb('lifecycle', 'foreground exit')
      telemetry.flush()
      return
    case OsEventTypeList.SYSTEM_EXIT_EVENT:
    case OsEventTypeList.ABNORMAL_EXIT_EVENT:
      log('exit event', type)
      telemetry.crumb('lifecycle', 'exit', { type })
      telemetry.flush()
      cleanup()
      return
    default:
      return
  }
})

window.addEventListener('beforeunload', cleanup)
socket.connect()
syncPhone()
