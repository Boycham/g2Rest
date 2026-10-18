import type { FloorState, TableState, TableStatus } from './contract'
import { DISPLAY_HEIGHT, DISPLAY_WIDTH, fit, type CardView } from './card'

// The manager's floor minimap: one bordered text container per table, placed from the
// floor plan's x/y, brightness from the backend's urgency. A page holds at most 8 text
// containers, so 8 tables is the limit (one of them also captures input).

export const MAX_TABLES = 8
export const BOX_W = 128
export const BOX_H = 64
export const BOX_BORDER = 1
export const BOX_PADDING = 4
export const BOX_TEXT_WIDTH = BOX_W - 2 * (BOX_BORDER + BOX_PADDING)
/** Urgency at which the glyph turns into "needs attention". */
export const ATTENTION_URGENCY = 4

export interface FloorTable {
  table: string
  status: TableStatus
  /** Epoch ms when the table entered its status. */
  since: number
  x: number
  y: number
  urgency: number
}

export interface Box {
  table: string
  x: number
  y: number
  w: number
  h: number
}

export interface BoxView extends Box, CardView {}

const GLYPHS: Record<TableStatus, string> = {
  empty: '-',
  seated: 'S',
  ordered: 'O',
  waiting: 'W',
  eating: 'E',
  check: 'C',
}

export const GLYPH_LEGEND: readonly [string, string][] = [
  ['!', 'needs you'],
  ['S', 'seated'],
  ['O', 'ordered'],
  ['W', 'waiting on food'],
  ['E', 'eating (mains out)'],
  ['C', 'check'],
  ['-', 'empty'],
]

const tableNum = (label: string) => Number(label.replace(/\D+/g, '')) || 0

/** Natural order (T2 before T10) so each table keeps the same container across updates. */
export function byLabel(a: { table: string }, b: { table: string }): number {
  return tableNum(a.table) - tableNum(b.table) || a.table.localeCompare(b.table)
}

export function applyFloor(msg: FloorState, now: number): FloorTable[] {
  return msg.tables
    .map((t: TableState) => ({
      table: t.table,
      status: t.status,
      since: now - t.sinceSec * 1000,
      x: t.x,
      y: t.y,
      urgency: t.urgency,
    }))
    .sort(byLabel)
    .slice(0, MAX_TABLES)
}

export function statusGlyph(t: Pick<FloorTable, 'status' | 'urgency'>): string {
  return t.urgency >= ATTENTION_URGENCY ? '!' : GLYPHS[t.status]
}

/**
 * Urgency 0..4 to text brightness 0..4. Level 0 is the fully dim level, so calm tables
 * sit at 1 to stay readable; only the table that needs the manager reaches 4.
 */
export function brightnessFor(urgency: number): number {
  return Math.max(1, Math.min(4, Math.round(urgency)))
}

export function minutesLabel(t: FloorTable, now: number): string {
  if (t.status === 'empty') return ''
  return `${Math.max(0, Math.floor((now - t.since) / 60_000))}m`
}

export function boxText(t: FloorTable, now: number): string {
  return [`${t.table} ${statusGlyph(t)}`, minutesLabel(t, now)].map(l => fit(l, BOX_TEXT_WIDTH)).join('\n')
}

function axis(v: number, min: number, max: number, span: number, size: number): number {
  const free = span - size
  return Math.round(max === min ? free / 2 : ((v - min) / (max - min)) * free)
}

/** Fit the floor plan's bounding box to the display; each table's box keeps its spot. */
export function layout(tables: readonly Pick<FloorTable, 'table' | 'x' | 'y'>[], width = DISPLAY_WIDTH, height = DISPLAY_HEIGHT): Box[] {
  if (!tables.length) return []
  const xs = tables.map(t => t.x)
  const ys = tables.map(t => t.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  return tables.map(t => ({
    table: t.table,
    x: axis(t.x, x0, x1, width, BOX_W),
    y: axis(t.y, y0, y1, height, BOX_H),
    w: BOX_W,
    h: BOX_H,
  }))
}

export function minimapView(tables: readonly FloorTable[], now: number): BoxView[] {
  const boxes = layout(tables)
  return tables.map((t, i) => ({ ...boxes[i]!, text: boxText(t, now), brightness: brightnessFor(t.urgency) }))
}

/** Changes only when a rebuild is needed (tables added, removed or moved). */
export function layoutKey(boxes: readonly Box[]): string {
  return boxes.map(b => `${b.table}@${b.x},${b.y}`).join('|')
}

/** Phone mirror, most urgent first. */
export function tableRows(tables: readonly FloorTable[], now: number): string[] {
  return [...tables]
    .sort((a, b) => b.urgency - a.urgency || byLabel(a, b))
    .map(t => `${t.table} ${statusGlyph(t)} ${t.status} ${minutesLabel(t, now)} (urgency ${t.urgency})`.replace(/\s+/g, ' '))
}
