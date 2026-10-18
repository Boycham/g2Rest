// Shared by the story and its scenes: the per-frame scroll callbacks and asset paths.
import { createContext, useContext, useEffect, useRef } from 'react'
import { SCENES, local, sceneOpacity } from './keyframes.js'

const ASSET = `${import.meta.env.BASE_URL}assets/`
export const asset = (name: string) => ASSET + name

export type Frame = (g: number) => void
type StoryCtx = {
  register: (fn: Frame) => () => void
  reduced: boolean
  /** Fade between scenes, in global progress; 0 with reduced motion. */
  fade: number
}
export const Ctx = createContext<StoryCtx>({ register: () => () => {}, reduced: false, fade: 0.025 })
export const useStory = () => useContext(Ctx)

/** Run fn(g) on every scroll frame. fn writes styles; it must not set React state. */
export function useFrame(fn: Frame) {
  const { register } = useStory()
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => register((g) => ref.current(g)), [register])
}

/** A scene's root: fades with global progress and hides itself when fully out. */
export function useSceneRoot(index: number) {
  const ref = useRef<HTMLElement>(null)
  const { fade } = useStory()
  useFrame((g) => {
    const el = ref.current
    if (!el) return
    const o = sceneOpacity(g, index, fade)
    el.style.opacity = String(o)
    el.style.visibility = o > 0 ? 'visible' : 'hidden'
  })
  return { ref, local: (g: number) => local(g, SCENES[index]) }
}
