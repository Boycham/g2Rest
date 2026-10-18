import { CAPTURE_AUDIO_FORMAT } from './contract'
import { log } from './log'

// DEV ONLY: a PCM fixture (backend/voice/fixtures, gitignored, served by the Vite dev server at
// /dev-fixtures/) stands in for the mic's last minute, because the simulator mic may not hear
// anything. Enabled by `?debugPcm=conv_task,conv_tableless`: the rolling buffer is filled with
// the first fixture, each swipe down clips it through the same path as mic audio, and the
// buffer is then refilled with the next fixture.

const FRAME = CAPTURE_AUDIO_FORMAT.frameBytes
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

/** The fixture as 100 ms frames, or [] (logged) if it can't be fetched. */
export async function loadFixture(name: string): Promise<ArrayBuffer[]> {
  try {
    const res = await fetch(`/dev-fixtures/${name}.pcm`, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const fs = frames(new Uint8Array(await res.arrayBuffer()))
    log('debug pcm', name, `${fs.length} frames (${(fs.length / 10).toFixed(1)} s), speech ends at frame ${lastVoicedFrame(fs)}`)
    return fs
  } catch (err) {
    log('debug pcm fetch failed', name, String(err))
    return []
  }
}
