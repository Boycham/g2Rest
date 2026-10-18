import { describe, expect, it } from 'vitest'
import { CLIP_FRAMES, RollingBuffer } from './clip'

const frame = (n: number) => {
  const f = new Uint8Array(3200)
  f[0] = n % 256
  f[1] = Math.floor(n / 256)
  return f.buffer
}
const ids = (fs: ArrayBuffer[]) => fs.map(f => new Uint8Array(f)[0]! + 256 * new Uint8Array(f)[1]!)

describe('RollingBuffer', () => {
  it('holds exactly the last 60 s and drops anything older as audio arrives', () => {
    const b = new RollingBuffer()
    expect(CLIP_FRAMES).toBe(600)
    for (let i = 0; i < 1000; i++) b.push(frame(i))
    const clip = b.clip()
    expect(clip).toHaveLength(600)
    expect(b.seconds).toBe(60)
    expect(ids(clip)[0]).toBe(400)
    expect(ids(clip).at(-1)).toBe(999)
  })

  it('returns a short clip oldest first before the minute has filled', () => {
    const b = new RollingBuffer(5)
    for (let i = 0; i < 3; i++) b.push(frame(i))
    expect(ids(b.clip())).toEqual([0, 1, 2])
    for (let i = 3; i < 8; i++) b.push(frame(i))
    expect(ids(b.clip())).toEqual([3, 4, 5, 6, 7])
  })

  it('keeps rolling after a clip and forgets everything on clear', () => {
    const b = new RollingBuffer(3)
    b.push(frame(1))
    b.clip()
    b.push(frame(2))
    expect(ids(b.clip())).toEqual([1, 2])
    b.clear()
    expect(b.clip()).toEqual([])
    expect(b.frames).toBe(0)
  })

  it('ignores frames that are not 100 ms of 16 kHz s16le', () => {
    const b = new RollingBuffer()
    b.push(new ArrayBuffer(100))
    expect(b.frames).toBe(0)
  })
})
