import type { EvenAppBridge } from '@evenrealities/even_hub_sdk'
import type { Task } from './contract'
import { parseTaskList } from './parse'
import { log } from './log'

// The Even app reloads the plugin in a hidden WebView when it goes to the background,
// so the queue is cached in SDK storage (not browser localStorage) for instant redraw.
// The backend stays the source of truth and re-sends open tasks on reconnect.

const QUEUE_KEY = 'fs.queue.v1'

export async function loadQueue(bridge: EvenAppBridge): Promise<Task[]> {
  try {
    const raw = await bridge.getLocalStorage(QUEUE_KEY)
    if (!raw) return []
    const tasks = parseTaskList(raw)
    if (!tasks) log('stored queue invalid; ignoring')
    return tasks ?? []
  } catch (err) {
    log('loadQueue failed', String(err))
    return []
  }
}

export async function saveQueue(bridge: EvenAppBridge, tasks: readonly Task[]): Promise<void> {
  try {
    const ok = await bridge.setLocalStorage(QUEUE_KEY, JSON.stringify(tasks))
    if (!ok) log('saveQueue returned false')
  } catch (err) {
    log('saveQueue failed', String(err))
  }
}
