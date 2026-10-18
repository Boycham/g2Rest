import type { EvenAppBridge, TextContainerProperty } from '@evenrealities/even_hub_sdk'
import type { BackendMessage } from './contract'
import type { BackendSocket, SocketStatus } from './socket'

export type Role = 'server' | 'manager'
export const ROLES: readonly Role[] = ['server', 'manager']

export interface PageSpec {
  containerTotalNum: number
  textObject: TextContainerProperty[]
}

export interface HudContext {
  bridge: EvenAppBridge
  socket: BackendSocket
  status(): SocketStatus
  /** True while this HUD's role is the one on the glasses. */
  active(): boolean
  syncPhone(): void
}

/** A role's glasses screens. The shell owns the socket, double tap and lifecycle events. */
export interface Hud {
  readonly role: Role
  screen(): string
  /** The root page, for `createStartUpPageContainer`; marks it as shown. */
  startPage(): PageSpec
  /** Become the active role: rebuild to the root screen. */
  enter(): Promise<void>
  /** Stop being the active role (e.g. close an open capture). */
  leave(): void
  /** Every backend message reaches both HUDs, so the inactive one stays current. */
  onMessage(msg: BackendMessage): void
  onStatus(): void
  onTap(): void
  onSwipeUp(): void
  onSwipeDown(): void
  /** Long hold (SDK LONG_PRESS_EVENT). */
  onLongPress(): void
  save(): void
  cleanup(): void
}
