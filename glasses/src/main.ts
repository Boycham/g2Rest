import {
  CreateStartUpPageContainer,
  OsEventTypeList,
  RebuildPageContainer,
  TextContainerProperty,
  TextContainerUpgrade,
  waitForEvenAppBridge,
  type EvenHubEvent,
} from '@evenrealities/even_hub_sdk'
import type { BackendMessage } from './contract'
import { CARD_PADDING, DISPLAY_HEIGHT, DISPLAY_WIDTH, formatCard, formatQueue } from './card'
import { BackendSocket, type SocketStatus } from './socket'
import { loadQueue, saveQueue } from './storage'
import { tap, type Queue } from './tasks'
import { applyBackendTask, loadDone, markDone, saveDone, type DoneIds } from './reconcile'
import { log } from './log'
import { mountUi, renderPhone } from './ui'
import { CaptureScreen } from './capture'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'ws://localhost:8787/ws'

type Screen = 'card' | 'queue' | 'draft'

const MAIN_ID = 1
const MAIN_NAME = 'main'

let queue: Queue = []
let done: DoneIds = []
let screen: Screen = 'card'
let status: SocketStatus = 'connecting'

mountUi(BACKEND_URL)
const bridge = await waitForEvenAppBridge()
queue = await loadQueue(bridge)
done = await loadDone(bridge)
log('restored queue', queue.length)

// ---------- glasses rendering ----------

function textPage(content: string, brightness = 4): TextContainerProperty {
  return new TextContainerProperty({
    xPosition: 0,
    yPosition: 0,
    width: DISPLAY_WIDTH,
    height: DISPLAY_HEIGHT,
    borderWidth: 0,
    paddingLength: CARD_PADDING,
    containerID: MAIN_ID,
    containerName: MAIN_NAME,
    // An empty string may be rejected by the host; a space renders as blank.
    content: content || ' ',
    textColor: brightness,
    isEventCapture: 1,
  })
}

function currentCard() {
  return formatCard(queue, { offline: status !== 'online' })
}

let shownCard = ''

const created = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({ containerTotalNum: 1, textObject: [textPage(currentCard().text, currentCard().brightness)] }),
)
shownCard = JSON.stringify(currentCard())
log('createStartUpPageContainer', created)

// Card writes are serialized and coalesced so a burst of messages ends on the latest card.
let writing = false
let dirty = false
async function renderCard(): Promise<void> {
  if (screen !== 'card') return
  if (writing) {
    dirty = true
    return
  }
  writing = true
  try {
    do {
      dirty = false
      const view = currentCard()
      const key = JSON.stringify(view)
      if (key === shownCard) continue
      const t0 = performance.now()
      const ok = await bridge.textContainerUpgrade(
        new TextContainerUpgrade({
          containerID: MAIN_ID,
          containerName: MAIN_NAME,
          content: view.text || ' ',
          textColor: view.brightness,
        }),
      )
      shownCard = key
      log('card upgrade', ok, `${(performance.now() - t0).toFixed(1)} ms`, JSON.stringify(view.text))
    } while (dirty && screen === 'card')
  } finally {
    writing = false
  }
}

async function showScreen(next: Screen): Promise<void> {
  if (screen === 'draft' && next !== 'draft') capture.leave()
  screen = next
  if (next === 'draft') {
    await capture.enter()
    syncPhone()
    return
  }
  const card = currentCard()
  const text = next === 'queue' ? formatQueue(queue) : card.text
  const brightness = next === 'card' ? card.brightness : 4
  const page = new RebuildPageContainer({ containerTotalNum: 1, textObject: [textPage(text, brightness)] })
  if (next === 'card') shownCard = JSON.stringify(card)
  const t0 = performance.now()
  const ok = await bridge.rebuildPageContainer(page)
  log('rebuild', next, ok, `${(performance.now() - t0).toFixed(1)} ms`)
  syncPhone()
}

function syncPhone(): void {
  renderPhone({ status, screen, queue, capturing: capture.capturing })
}

function changed(): void {
  void saveQueue(bridge, queue)
  void saveDone(bridge, done)
  void renderCard()
  syncPhone()
}

// ---------- backend ----------

function onBackend(msg: BackendMessage): void {
  switch (msg.type) {
    case 'task.assigned':
    case 'task.updated':
      log('<-', msg.type, msg.task.id, msg.task.state)
      {
        const r = applyBackendTask(queue, done, msg.task)
        queue = r.queue
        done = r.done
        for (const m of r.resend) socket.send(m)
        if (r.resend.length) log('re-sent after replay', r.resend.map(m => m.type).join(' '))
      }
      changed()
      return
    case 'order.draft':
      log('<-', msg.type, msg.orderId, msg.voice ?? '', `${msg.lines.length} lines`, `${msg.pending?.length ?? 0} pending`)
      capture.onDraft(msg)
      return
    default:
      log('<- unhandled on server HUD', msg.type)
  }
}

const socket = new BackendSocket(BACKEND_URL, {
  onMessage: onBackend,
  onStatus: s => {
    status = s
    log('status', s)
    capture.setOnline(s === 'online')
    void renderCard()
    syncPhone()
  },
})

const capture = new CaptureScreen(bridge, socket, syncPhone)

// ---------- gestures ----------

async function startCapture(): Promise<void> {
  await showScreen('draft')
  capture.start()
}

function onDraftGesture(g: 'tap' | 'up' | 'down'): void {
  if (capture.gesture(g) === 'back') void showScreen('card')
}

function onTap(): void {
  if (screen === 'draft') return onDraftGesture('tap')
  if (screen === 'queue') {
    void showScreen('card')
    return
  }
  if (screen !== 'card') return
  const r = tap(queue)
  queue = r.queue
  if (r.send) socket.send(r.send)
  if (r.send?.type === 'task.done') done = markDone(done, r.send.taskId)
  changed()
}

function onSwipeUp(): void {
  if (screen === 'draft') onDraftGesture('up')
  else if (screen === 'card') void showScreen('queue')
  else if (screen === 'queue') void showScreen('card')
}

function onSwipeDown(): void {
  if (screen === 'card') void startCapture()
  else if (screen === 'draft') onDraftGesture('down')
}

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
  capture.stop()
  void saveQueue(bridge, queue)
}

bridge.onEvenHubEvent(event => {
  if (event.audioEvent) return capture.onAudio(event.audioEvent.audioPcm)
  const type = eventTypeOf(event)
  if (type === null) return
  switch (type) {
    case OsEventTypeList.DOUBLE_CLICK_EVENT:
      // Even Hub review rule: double tap exits through the system dialog, nothing else.
      log('double tap -> shutDownPageContainer(1)')
      void bridge.shutDownPageContainer(1)
      return
    case OsEventTypeList.CLICK_EVENT:
      log('tap on', screen)
      return onTap()
    case OsEventTypeList.SCROLL_TOP_EVENT:
      log('swipe up on', screen)
      return onSwipeUp()
    case OsEventTypeList.SCROLL_BOTTOM_EVENT:
      log('swipe down on', screen)
      return onSwipeDown()
    case OsEventTypeList.FOREGROUND_ENTER_EVENT:
      log('foreground enter: reconnecting')
      socket.reconnectNow()
      return
    case OsEventTypeList.FOREGROUND_EXIT_EVENT:
      log('foreground exit: mic off, saving queue')
      capture.stop()
      void saveQueue(bridge, queue)
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
