import { describe, expect, it } from 'vitest'
import { FrameChunker, toBytes } from './mic'
import { frames, lastVoicedFrame } from './debug-pcm'

describe('FrameChunker', () => {
  it('re-cuts odd chunk sizes into exact 3200-byte frames', () => {
    const c = new FrameChunker()
    expect(c.push(new Uint8Array(1000))).toEqual([])
    const out = c.push(new Uint8Array(6000))
    expect(out.map(f => f.byteLength)).toEqual([3200, 3200])
    expect(c.push(new Uint8Array(2600)).map(f => f.byteLength)).toEqual([3200])
  })

  it('keeps byte order across chunk boundaries', () => {
    const c = new FrameChunker()
    const a = Uint8Array.from({ length: 2000 }, (_, i) => i % 251)
    const b = Uint8Array.from({ length: 1200 }, (_, i) => (i + 2000) % 251)
    const [f] = c.push(a).concat(c.push(b))
    expect(new Uint8Array(f)[1999]).toBe(1999 % 251)
    expect(new Uint8Array(f)[2000]).toBe(2000 % 251)
  })
})

describe('toBytes', () => {
  it('accepts Uint8Array, number[] and base64', () => {
    expect(toBytes(new Uint8Array([1, 2]))).toEqual(new Uint8Array([1, 2]))
    expect(toBytes([1, 2])).toEqual(new Uint8Array([1, 2]))
    expect(toBytes(btoa('\x01\x02'))).toEqual(new Uint8Array([1, 2]))
    expect(toBytes({})).toBeNull()
  })
})

describe('debug pcm', () => {
  it('pads the last frame and finds the end of speech', () => {
    const pcm = new Uint8Array(3200 * 2 + 10)
    const loud = new Int16Array(pcm.buffer, 3200, 1600)
    loud.fill(8000)
    const fs = frames(pcm)
    expect(fs.map(f => f.byteLength)).toEqual([3200, 3200, 3200])
    expect(lastVoicedFrame(fs)).toBe(1)
  })
})
