import { CAPTURE_AUDIO_FORMAT } from './contract'
import { log } from './log'

// DEV ONLY: stream a PCM fixture (backend/voice/fixtures, gitignored, served by the Vite
// dev server at /dev-fixtures/) through the same capture path as the mic, because the
// simulator mic may not hear anything. Enabled by `?debugPcm=01_order,02_no_soup,...`:
// each capture plays the next fixture, then sends silence like a quiet mic until stopped.

const FRAME = CAPTURE_AUDIO_FORMAT.frameBytes
const FRAME_MS = 100
const VOICED_DBFS = -40
const FETCH_TIMEOUT_MS = 5000

export function debugFixtures(search = location.search): string[] {
  if (!import.meta.env.DEV) return []
  const raw = new URLSearchParams(search).get('debugPcm')
  return raw ? raw.split(',').filter(n => /^[\w-]+$/.test(n)) : []
}

export function frames(pcm: Uint8Array): ArrayBuffer[] {
  const out: ArrayBuffer[] = []
  for (let i = 0; i < pcm.length; i += FRAME) {
    const f = new Uint8Array(FRAME)
    f.set(pcm.subarray(i, i + FRAME))
    out.push(f.buffer)
  }
  return out
}

/** Index of the last 100 ms frame above -40 dBFS (the "end of speech"), or -1. */
export function lastVoicedFrame(fs: readonly ArrayBuffer[]): number {
  let last = -1
  fs.forEach((f, i) => {
    const s = new Int16Array(f)
    let sum = 0
    for (const x of s) sum += x * x
    const rms = Math.sqrt(sum / s.length) || 1e-9
    if (20 * Math.log10(rms / 32768) > VOICED_DBFS) last = i
  })
  return last
}

export interface DebugStream {
  stop(): void
}

/** Streams in real time; calls onSpeechEnd(performance.now()) as the last voiced frame goes out. */
export function streamFixture(
  name: string,
  onFrame: (frame: ArrayBuffer) => void,
  onSpeechEnd: (t: number) => void,
): DebugStream {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | null = null
  const stop = () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
  void (async () => {
    let fs: ArrayBuffer[] = []
    try {
      const res = await fetch(`/dev-fixtures/${name}.pcm`, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      fs = frames(new Uint8Array(await res.arrayBuffer()))
    } catch (err) {
      log('debug pcm fetch failed', name, String(err))
    }
    const end = lastVoicedFrame(fs)
    log('debug pcm', name, `${fs.length} frames, speech ends at frame ${end}`)
    const silence = new ArrayBuffer(FRAME)
    const t0 = performance.now()
    let n = 0
    const tick = () => {
      if (stopped) return
      onFrame(n < fs.length ? fs[n] : silence)
      if (n === end) onSpeechEnd(performance.now())
      n += 1
      timer = setTimeout(tick, Math.max(0, t0 + n * FRAME_MS - performance.now()))
    }
    tick()
  })()
  return { stop }
}
