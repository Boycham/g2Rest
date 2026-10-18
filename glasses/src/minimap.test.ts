import { describe, expect, it } from 'vitest'
import { getTextWidth } from '@evenrealities/pretext'
import type { TableState } from './contract'
import { DISPLAY_HEIGHT, DISPLAY_WIDTH } from './card'
import {
  BOX_H,
  BOX_TEXT_WIDTH,
  BOX_W,
  MAX_TABLES,
  applyFloor,
  boxText,
  brightnessFor,
  layout,
  layoutKey,
  minimapView,
  statusGlyph,
} from './minimap'

const T0 = 5_000_000
const table = (n: number, over: Partial<TableState> = {}): TableState => ({
  table: `T${n}`,
  status: 'seated',
  sinceSec: 0,
  x: (n - 1) % 4,
  y: Math.floor((n - 1) / 4),
  urgency: 0,
  ...over,
})
const floor = (tables: TableState[]) => applyFloor({ type: 'floor.state', tables }, T0)
const eight = () => Array.from({ length: 8 }, (_, i) => table(i + 1))

describe('minimap layout', () => {
  it('fits a 4x2 floor plan to the display corners without overlap', () => {
    const boxes = layout(floor(eight()))
    expect(boxes[0]).toMatchObject({ table: 'T1', x: 0, y: 0, w: BOX_W, h: BOX_H })
    expect(boxes[7]).toMatchObject({ table: 'T8', x: DISPLAY_WIDTH - BOX_W, y: DISPLAY_HEIGHT - BOX_H })
    for (const b of boxes) {
      expect(b.x).toBeGreaterThanOrEqual(0)
      expect(b.y).toBeGreaterThanOrEqual(0)
      expect(b.x + b.w).toBeLessThanOrEqual(DISPLAY_WIDTH)
      expect(b.y + b.h).toBeLessThanOrEqual(DISPLAY_HEIGHT)
    }
    for (const a of boxes)
      for (const b of boxes) {
        if (a === b) continue
        const apart = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y
        expect(apart, `${a.table} overlaps ${b.table}`).toBe(true)
      }
  })

  it('accepts any floor-plan unit and keeps relative positions', () => {
    const boxes = layout(floor([table(1, { x: 100, y: 40 }), table(2, { x: 300, y: 40 }), table(3, { x: 200, y: 90 })]))
    expect(boxes.map(b => b.x)).toEqual([0, DISPLAY_WIDTH - BOX_W, (DISPLAY_WIDTH - BOX_W) / 2])
    expect(boxes.map(b => b.y)).toEqual([0, 0, DISPLAY_HEIGHT - BOX_H])
  })

  it('centres a single table, or a row with no height', () => {
    const [only] = layout(floor([table(1)]))
    expect(only).toMatchObject({ x: (DISPLAY_WIDTH - BOX_W) / 2, y: (DISPLAY_HEIGHT - BOX_H) / 2 })
    expect(layout(floor([table(1), table(2)])).map(b => b.y)).toEqual([(DISPLAY_HEIGHT - BOX_H) / 2, (DISPLAY_HEIGHT - BOX_H) / 2])
    expect(layout([])).toEqual([])
  })

  it('keeps tables in natural order and caps at the 8-container limit', () => {
    const tables = floor([table(10), table(2), ...Array.from({ length: 8 }, (_, i) => table(i + 11))])
    expect(tables).toHaveLength(MAX_TABLES)
    expect(tables.slice(0, 3).map(t => t.table)).toEqual(['T2', 'T10', 'T11'])
  })

  it('layout key changes on a move, not on a status or urgency change', () => {
    const base = layoutKey(layout(floor(eight())))
    const busier = eight().map(t => ({ ...t, status: 'waiting' as const, urgency: 4, sinceSec: 900 }))
    expect(layoutKey(layout(floor(busier)))).toBe(base)
    const moved = eight().map((t, i) => (i === 0 ? { ...t, x: 1.5 } : t))
    expect(layoutKey(layout(floor(moved)))).not.toBe(base)
  })
})

describe('minimap brightness and glyphs', () => {
  it('maps urgency to the 5 brightness levels, calm tables still visible', () => {
    expect([0, 1, 2, 3, 4].map(brightnessFor)).toEqual([1, 1, 2, 3, 4])
    expect(brightnessFor(9)).toBe(4)
    expect(brightnessFor(-1)).toBe(1)
  })

  it('the late table is the single brightest box', () => {
    const tables = eight().map(t => (t.table === 'T4' ? { ...t, status: 'waiting' as const, urgency: 4 } : { ...t, urgency: 1 }))
    const views = minimapView(floor(tables), T0)
    const max = Math.max(...views.map(v => v.brightness))
    expect(views.filter(v => v.brightness === max).map(v => v.table)).toEqual(['T4'])
  })

  it('shows one status glyph, ! when the table needs the manager', () => {
    expect(statusGlyph({ status: 'seated', urgency: 0 })).toBe('S')
    expect(statusGlyph({ status: 'ordered', urgency: 2 })).toBe('O')
    expect(statusGlyph({ status: 'waiting', urgency: 3 })).toBe('W')
    expect(statusGlyph({ status: 'eating', urgency: 0 })).toBe('E')
    expect(statusGlyph({ status: 'waiting', urgency: 4 })).toBe('!')
  })

  it('box shows table, glyph and minutes, and ticks locally', () => {
    const [t4] = floor([table(4, { status: 'waiting', sinceSec: 14 * 60 + 30, urgency: 4 })])
    expect(boxText(t4!, T0)).toBe('T4 !\n14m')
    expect(boxText(t4!, T0 + 60_000)).toBe('T4 !\n15m')
    const [empty] = floor([table(5, { status: 'empty', sinceSec: 600 })])
    expect(boxText(empty!, T0)).toBe('T5 -\n')
  })

  it('box lines fit inside the box', () => {
    const [t] = floor([table(1, { table: 'Patio-Long-Table-12', sinceSec: 999 * 60 })])
    for (const line of boxText(t!, T0).split('\n')) expect(getTextWidth(line)).toBeLessThanOrEqual(BOX_TEXT_WIDTH)
  })
})
