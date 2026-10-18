// The scroll story's motion, taken from the Paper file's Developer Handoff page.
// Every scene was drawn as five artboards (KF 0/25/50/75/100) on a 1440x900 stage; between
// them each layer's left/top/width/height/opacity moves linearly. Pure, so `node --test` runs it.

export const STAGE = { w: 1440, h: 900 }
export const CENTER = { x: 720, y: 450 }
export const KEYS = [0, 0.25, 0.5, 0.75, 1]

/** Global scroll split from the handoff: the doors scene gets the longest stretch. */
export const SCENES = [
  { id: 'welcome', label: 'Welcome', start: 0, end: 0.2 },
  { id: 'counter', label: 'Tasks', start: 0.2, end: 0.4 },
  { id: 'voice', label: 'Voice', start: 0.4, end: 0.6 },
  { id: 'doors', label: 'Inside', start: 0.6, end: 0.85 },
  { id: 'floor', label: 'Floor', start: 0.85, end: 1 },
]

export const clamp01 = (t) => Math.min(1, Math.max(0, t))
export const lerp = (a, b, t) => a + (b - a) * t

/** Scene-local progress 0..1 for global progress g. */
export function local(g, scene) {
  return clamp01((g - scene.start) / (scene.end - scene.start))
}

/** Index of the scene that owns global progress g. */
export function sceneIndex(g) {
  const i = SCENES.findIndex((s) => g < s.end)
  return i === -1 ? SCENES.length - 1 : i
}

/**
 * A scene's opacity: 1 inside its range, crossfading over `fade` of global progress at each
 * inner boundary, so one scene's KF100 dissolves into the next scene's KF0.
 */
export function sceneOpacity(g, index, fade = 0.025) {
  const s = SCENES[index]
  if (fade <= 0) return sceneIndex(g) === index ? 1 : 0
  const into = index === 0 ? 1 : clamp01((g - (s.start - fade)) / fade)
  const out = index === SCENES.length - 1 ? 1 : clamp01((s.end + fade - g) / fade)
  return Math.min(into, out)
}

/** Piecewise-linear value through the five keyframes. */
export function track(values, t) {
  const x = clamp01(t) * (values.length - 1)
  const i = Math.min(values.length - 2, Math.floor(x))
  return lerp(values[i], values[i + 1], x - i)
}

/** Piecewise-linear rect [left, top, width, height] through five keyframe rects. */
export function rectTrack(rects, t) {
  return [0, 1, 2, 3].map((k) =>
    track(
      rects.map((r) => r[k]),
      t,
    ),
  )
}

/** The keyframe a discrete state belongs to: text swaps at the midpoint between keyframes. */
export function step(t) {
  return Math.round(clamp01(t) * 4)
}

/**
 * The handoff's camera rule: a point P on the KF0 artboard lands at (720,450) + s*(P - c)
 * for zoom s about the vanishing point c.
 */
export function camera(rect, s, c) {
  const [l, tp, w, h] = rect
  return [CENTER.x + s * (l - c.x), CENTER.y + s * (tp - c.y), w * s, h * s]
}

/** Zoom about the stage centre (the same rule with c = the centre). */
export function zoom(rect, s) {
  return camera(rect, s, CENTER)
}

/** A child placed relative to its parent's KF0 rect, following the parent's current rect. */
export function follow(parent0, child0, parentNow) {
  const sx = parentNow[2] / parent0[2]
  const sy = parentNow[3] / parent0[3]
  return [
    parentNow[0] + (child0[0] - parent0[0]) * sx,
    parentNow[1] + (child0[1] - parent0[1]) * sy,
    child0[2] * sx,
    child0[3] * sy,
  ]
}

// The photo plates are 16:9 and sit under the 76px nav at KF0.
export const PLATE0 = [-12, 76, 1465, 824]

export const WELCOME = {
  photo: [PLATE0, [-170, -35, 1795, 1009], [-326, -155, 2124, 1195], [-480, -286, 2454, 1380], [-631, -426, 2784, 1566]],
  sign0: [625, 112, 180, 79],
}

export function welcomeLayers(t) {
  const photo = rectTrack(WELCOME.photo, t)
  return { photo, sign: follow(PLATE0, WELCOME.sign0, photo) }
}

export function counterLayers(t) {
  const s = 1 + 0.35 * t
  const photo = camera(PLATE0, s, { x: 720 - 80 * t, y: 450 + 70 * t })
  return {
    photo,
    card: track([0, 1, 1, 1, 0.4], t),
    gesture: track([0, 1, 1, 1, 1], t),
    next: track([0, 0, 0, 0, 1], t),
  }
}

export function voiceLayers(t) {
  const s = 1 + 0.25 * t
  return { photo: camera(PLATE0, s, { x: 720 + 40 * t, y: 450 + 30 * t }) }
}

export const DOORS = { open: [0, 0.22, 0.55, 0.9, 1], shade: [0.62, 0.5, 0.3, 0.08, 0], copy: [0, 0, 0, 1, 1] }

export function doorsLayers(t) {
  const p = track(DOORS.open, t)
  return {
    interior: zoom(PLATE0, 1 + 0.08 * t),
    shade: track(DOORS.shade, t),
    left: -760 * p,
    right: 720 + 760 * p,
    copy: track(DOORS.copy, t),
  }
}

export const FLOOR = {
  overhead0: [-80, 0, 1600, 900],
  overheadScale: [1.25, 1.18, 1.1, 1.04, 1],
  overheadOpacity: [0, 0.5, 1, 1, 1],
  interiorScale: [1.08, 1.2, 1.35, 1.5, 1.5],
  interiorOpacity: [1, 0.6, 0, 0, 0],
  pins: [0, 0, 1, 1, 1],
  copy: [0, 0, 0, 1, 1],
  sign: [0, 0, 0, 0, 1],
}

/** Pins sit on the overhead plate, so they ride its zoom. */
export const PINS = [
  { id: '01', x: 242, y: 244, tone: 'stone' },
  { id: '02', x: 540, y: 244, tone: 'leaf' },
  { id: '03', x: 852, y: 244, tone: 'bone' },
  { id: '04', x: 1152, y: 244, tone: 'red' },
  { id: '05', x: 242, y: 548, tone: 'leaf' },
  { id: '06', x: 540, y: 548, tone: 'stone' },
  { id: '07', x: 852, y: 548, tone: 'stone' },
  { id: '08', x: 1152, y: 548, tone: 'stone' },
]

export function floorLayers(t) {
  const s = track(FLOOR.overheadScale, t)
  return {
    overhead: zoom(FLOOR.overhead0, s),
    overheadScale: s,
    overheadOpacity: track(FLOOR.overheadOpacity, t),
    interior: zoom(PLATE0, track(FLOOR.interiorScale, t)),
    interiorOpacity: track(FLOOR.interiorOpacity, t),
    pins: track(FLOOR.pins, t),
    copy: track(FLOOR.copy, t),
    sign: track(FLOOR.sign, t),
  }
}

/** Where a stage point lands after a zoom about the centre. */
export function zoomPoint(x, y, s) {
  return [CENTER.x + s * (x - CENTER.x), CENTER.y + s * (y - CENTER.y)]
}

/**
 * Per scene, the first keyframe where every one of its layers is in: the welcome at KF0, the
 * task card at KF25, the full ticket at KF75, the doors' copy at KF75, the dashboard sign at
 * KF100. The scene dots land here, and reduced motion holds each scene here.
 */
export const BUILT = [0, 0.25, 0.75, 0.75, 1]

/** Global progress where scene `index` is fully built. Stays inside the scene's own range. */
export function builtAt(index) {
  const s = SCENES[index]
  return +(s.start + BUILT[index] * (s.end - s.start)).toFixed(4)
}

/** Every keyframe as a global progress value: the snap points for "scroll to the next page". */
export function snapPoints() {
  const out = new Set()
  for (const s of SCENES) for (const k of KEYS) out.add(+(s.start + k * (s.end - s.start)).toFixed(4))
  return [...out].sort((a, b) => a - b)
}
