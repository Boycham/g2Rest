import {
  CreateStartUpPageContainer,
  ListContainerProperty,
  ListItemContainerProperty,
  OsEventTypeList,
  RebuildPageContainer,
  TextContainerProperty,
  TextContainerUpgrade,
  waitForEvenAppBridge,
  type EvenHubEvent,
} from '@evenrealities/even_hub_sdk'
import type { BackendMessage } from './contract'
import { CARD_PADDING, CARD_TEXT_WIDTH, DISPLAY_HEIGHT, DISPLAY_WIDTH, formatCard, queueRow } from './card'
import { BackendSocket, type SocketStatus } from './socket'
import { loadQueue, saveQueue } from './storage'
import { tap, upsertTask, type Queue } from './tasks'
import { log } from './log'
import { mountUi, renderPhone } from './ui'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'ws://localhost:8787/ws'

type Screen = 'card' | 'queue' | 'listening'

const MAIN_ID = 1
const MAIN_NAME = 'main'
const LIST_MAX_ITEMS = 20
const LISTENING_TEXT = 'Listening… (swipe down to stop)'

let queue: Queue = []
let screen: Screen = 'card'
let status: SocketStatus = 'connecting'
let captureId: string | null = null

mountUi(BACKEND_URL)
const bridge = await waitForEvenAppBridge()
queue = await loadQueue(bridge)
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
  screen = next
  let page: RebuildPageContainer
  if (next === 'queue' && queue.length) {
    const rows = queue.slice(0, LIST_MAX_ITEMS).map(t => queueRow(t, CARD_TEXT_WIDTH - 2 * CARD_PADDING))
    page = new RebuildPageContainer({
      containerTotalNum: 1,
      listObject: [
        new ListContainerProperty({
          xPosition: 0,
          yPosition: 0,
          width: DISPLAY_WIDTH,
          height: DISPLAY_HEIGHT,
          borderWidth: 0,
          paddingLength: CARD_PADDING,
          containerID: MAIN_ID,
          containerName: MAIN_NAME,
          itemContainer: new ListItemContainerProperty({
            itemCount: rows.length,
            itemWidth: DISPLAY_WIDTH - 2 * CARD_PADDING,
            isItemSelectBorderEn: 1,
            itemName: rows,
          }),
          isEventCapture: 1,
        }),
      ],
    })
  } else {
    const text = next === 'listening' ? LISTENING_TEXT : next === 'queue' ? 'Queue empty' : currentCard().text
    const brightness = next === 'card' ? currentCard().brightness : 4
    page = new RebuildPageContainer({ containerTotalNum: 1, textObject: [textPage(text, brightness)] })
    if (next === 'card') shownCard = JSON.stringify(currentCard())
  }
  const t0 = performance.now()
  const ok = await bridge.rebuildPageContainer(page)
  log('rebuild', next, ok, `${(performance.now() - t0).toFixed(1)} ms`)
  syncPhone()
}

function syncPhone(): void {
  renderPhone({ status, screen, queue, capturing: captureId !== null })
}

function changed(): void {
  void saveQueue(bridge, queue)
  void renderCard()
  syncPhone()
}

// ---------- backend ----------

function onBackend(msg: BackendMessage): void {
  switch (msg.type) {
    case 'task.assigned':
    case 'task.updated':
      log('<-', msg.type, msg.task.id, msg.task.state)
      queue = upsertTask(queue, msg.task)
      changed()
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
    void renderCard()
    syncPhone()
  },
})

// ---------- gestures ----------

function newCaptureId(): string {
  return `cap-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function startCapture(): void {
  captureId = newCaptureId()
  socket.send({ type: 'capture.start', captureId })
  void showScreen('listening')
}

function stopCapture(): void {
  if (captureId) socket.send({ type: 'capture.stop', captureId })
  captureId = null
}

function onTap(): void {
  if (screen === 'queue') {
    void showScreen('card')
    return
  }
  if (screen !== 'card') return
  const r = tap(queue)
  queue = r.queue
  if (r.send) socket.send(r.send)
  changed()
}

function onSwipeUp(): void {
  if (screen === 'card') void showScreen('queue')
  else if (screen === 'queue') void showScreen('card')
}

function onSwipeDown(): void {
  if (screen === 'card') startCapture()
  else if (screen === 'listening') {
    stopCapture()
    void showScreen('card')
  }
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
  stopCapture()
  void saveQueue(bridge, queue)
}

bridge.onEvenHubEvent(event => {
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
      log('foreground exit: saving queue')
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
