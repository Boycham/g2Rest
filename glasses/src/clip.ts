import { CAPTURE_AUDIO_FORMAT } from './contract'

// The always-on mic's last minute, held in WebView memory only. Nothing is written to SDK
// storage, browser storage or disk; a swipe down copies the minute out as one clip, and
// anything older than 60 s is overwritten frame by frame as new audio arrives.

const FRAME = CAPTURE_AUDIO_FORMAT.frameBytes
export const CLIP_SECONDS = 60
const FRAMES_PER_SECOND = 1000 / 100
export const CLIP_FRAMES = CLIP_SECONDS * FRAMES_PER_SECOND

/**
 * A fixed ring of 100 ms frame slots. Each push replaces the oldest frame, so the buffer
 * never holds more than the last minute and never concatenates audio per frame (a
 * concatenating buffer once blocked the event loop; see the skill's 05 file).
 */
export class RollingBuffer {
  private readonly slots: (ArrayBuffer | null)[]
  private next = 0
  private count = 0

  constructor(readonly capacity = CLIP_FRAMES) {
    this.slots = new Array<ArrayBuffer | null>(capacity).fill(null)
  }

  get frames(): number {
    return this.count
  }

  get seconds(): number {
    return this.count / FRAMES_PER_SECOND
  }

  push(frame: ArrayBuffer): void {
    if (frame.byteLength !== FRAME) return
    this.slots[this.next] = frame
    this.next = (this.next + 1) % this.capacity
    this.count = Math.min(this.count + 1, this.capacity)
  }

  /** The buffered audio, oldest frame first. The buffer keeps rolling. */
  clip(): ArrayBuffer[] {
    const start = (this.next - this.count + this.capacity) % this.capacity
    const out: ArrayBuffer[] = []
    for (let i = 0; i < this.count; i++) out.push(this.slots[(start + i) % this.capacity]!)
    return out
  }

  clear(): void {
    this.slots.fill(null)
    this.next = 0
    this.count = 0
  }
}
