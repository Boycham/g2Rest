import type { EvenAppBridge } from '@evenrealities/even_hub_sdk'
import type { Task } from './contract'
import { EMPTY_EXCEPTIONS, type Exceptions } from './exceptions'
import type { Role } from './hud'
import type { FloorTable } from './minimap'
import { parseManagerCache, parseRole, parseTaskList } from './parse'
import { log } from './log'

// The Even app reloads the plugin in a hidden WebView when it goes to the background,
// so state is cached in SDK storage (not browser localStorage) for instant redraw.
// The backend stays the source of truth and re-sends open state on reconnect.

const QUEUE_KEY = 'fs.queue.v1'
const ROLE_KEY = 'fs.role.v1'
const MANAGER_KEY = 'fs.manager.v1'

export interface ManagerCache {
  exceptions: Exceptions
  tables: FloorTable[]
}

async function load<T>(bridge: EvenAppBridge, key: string, parse: (raw: string) => T | null, fallback: T): Promise<T> {
  try {
    const raw = await bridge.getLocalStorage(key)
    if (!raw) return fallback
    const value = parse(raw)
    if (value === null) log('stored', key, 'invalid; ignoring')
    return value ?? fallback
  } catch (err) {
    log('load', key, 'failed', String(err))
    return fallback
  }
}

async function save(bridge: EvenAppBridge, key: string, value: unknown): Promise<void> {
  try {
    const ok = await bridge.setLocalStorage(key, typeof value === 'string' ? value : JSON.stringify(value))
    if (!ok) log('save', key, 'returned false')
  } catch (err) {
    log('save', key, 'failed', String(err))
  }
}

export const loadQueue = (bridge: EvenAppBridge): Promise<Task[]> => load(bridge, QUEUE_KEY, parseTaskList, [])
export const saveQueue = (bridge: EvenAppBridge, tasks: readonly Task[]) => save(bridge, QUEUE_KEY, tasks)

/** Server stays the default so an unconfigured install behaves exactly as before. */
export const loadRole = (bridge: EvenAppBridge): Promise<Role> => load(bridge, ROLE_KEY, parseRole, 'server')
export const saveRole = (bridge: EvenAppBridge, role: Role) => save(bridge, ROLE_KEY, role)

export const loadManager = (bridge: EvenAppBridge): Promise<ManagerCache> =>
  load(bridge, MANAGER_KEY, parseManagerCache, { exceptions: EMPTY_EXCEPTIONS, tables: [] })
export const saveManager = (bridge: EvenAppBridge, cache: ManagerCache) => save(bridge, MANAGER_KEY, cache)
