import { AudioInputSource, type EvenAppBridge } from '@evenrealities/even_hub_sdk'
import { CAPTURE_AUDIO_FORMAT } from './contract'
import { log } from './log'

const FRAME = CAPTURE_AUDIO_FORMAT.frameBytes
const CONTROL_TIMEOUT_MS = 3000

/** The host may hand PCM over as Uint8Array, number[] or base64; normalize to bytes. */
export function toBytes(pcm: unknown): Uint8Array | null {
  if (pcm instanceof Uint8Array) return pcm
  if (Array.isArray(pcm) && pcm.every(n => Number.isInteger(n))) return Uint8Array.from(pcm as number[])
  if (typeof pcm === 'string') {
    try {
      return Uint8Array.from(atob(pcm), c => c.charCodeAt(0))
    } catch {
      return null
    }
  }
  return null
}

/** Re-cuts whatever chunk sizes the host delivers into exact 3200-byte (100 ms) frames. */
export class FrameChunker {
  private buf = new Uint8Array(0)

  push(chunk: Uint8Array): ArrayBuffer[] {
    const joined = new Uint8Array(this.buf.length + chunk.length)
    joined.set(this.buf)
    joined.set(chunk, this.buf.length)
    const frames: ArrayBuffer[] = []
    let i = 0
    for (; i + FRAME <= joined.length; i += FRAME) frames.push(joined.slice(i, i + FRAME).buffer)
    this.buf = joined.slice(i)
    return frames
  }

  reset(): void {
    this.buf = new Uint8Array(0)
  }
}

/** The G2 mic through the SDK's audioControl. Every call has a timeout. */
export class Mic {
  private open = false

  constructor(private readonly bridge: EvenAppBridge) {}

  get isOpen(): boolean {
    return this.open
  }

  async set(open: boolean): Promise<boolean> {
    if (open === this.open) return true
    this.open = open
    const timeout = new Promise<boolean>(resolve => setTimeout(() => resolve(false), CONTROL_TIMEOUT_MS))
    try {
      const ok = await Promise.race([this.bridge.audioControl(open, AudioInputSource.Glasses), timeout])
      log('audioControl', open ? 'on' : 'off', ok)
      if (!ok && open) this.open = false
      return ok
    } catch (err) {
      log('audioControl failed', open, String(err))
      if (open) this.open = false
      return false
    }
  }
}
