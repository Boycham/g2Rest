import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  PLATE0,
  SCENES,
  counterLayers,
  doorsLayers,
  floorLayers,
  local,
  rectTrack,
  sceneIndex,
  sceneOpacity,
  snapPoints,
  step,
  track,
  voiceLayers,
  welcomeLayers,
} from '../src/site/keyframes.js'

const near = (a, b, eps = 1.5) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`)
const nearRect = (a, b, eps) => a.forEach((v, i) => near(v, b[i], eps))

test('the global split matches the handoff', () => {
  assert.deepEqual(
    SCENES.map((s) => [s.start, s.end]),
    [
      [0, 0.2],
      [0.2, 0.4],
      [0.4, 0.6],
      [0.6, 0.85],
      [0.85, 1],
    ],
  )
  assert.equal(sceneIndex(0), 0)
  assert.equal(sceneIndex(0.2), 1)
  assert.equal(sceneIndex(0.84), 3)
  assert.equal(sceneIndex(1), 4)
  near(local(0.725, SCENES[3]), 0.5, 1e-9)
})

test('track and rectTrack pass through every keyframe and interpolate linearly', () => {
  const v = [0, 1, 1, 1, 0.4]
  assert.equal(track(v, 0), 0)
  assert.equal(track(v, 0.125), 0.5)
  assert.equal(track(v, 1), 0.4)
  near(track(v, 0.875), 0.7, 1e-9)
  assert.deepEqual(rectTrack([[0, 0, 10, 10], [10, 10, 20, 20], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], 0.125), [5, 5, 15, 15])
})

test('S01 photo hits the Paper keyframe rects; the sign rides it', () => {
  nearRect(welcomeLayers(0).photo, PLATE0, 0.01)
  nearRect(welcomeLayers(0.5).photo, [-326, -155, 2124, 1195], 0.01)
  const { photo, sign } = welcomeLayers(1)
  nearRect(photo, [-631, -426, 2784, 1566], 0.01)
  near(sign[2], 180 * (2784 / 1465), 0.01)
})

test('S02 and S03 cameras reproduce the artboards (P\' = 720,450 + s(P - c))', () => {
  nearRect(counterLayers(0.25).photo, [-54, 24, 1593, 896])
  nearRect(counterLayers(1).photo, [-160, -149, 1978, 1112])
  nearRect(voiceLayers(0.25).photo, [-68, 45, 1557, 876])
  nearRect(voiceLayers(0.75).photo, [-185, -21, 1740, 978])
  nearRect(voiceLayers(1).photo, [-245, -55, 1831, 1030])
  assert.deepEqual([0, 0.25, 0.5, 0.75, 1].map((t) => counterLayers(t).card), [0, 1, 1, 1, 0.4])
})

test('S04 doors part by 760px; copy arrives at KF75', () => {
  assert.equal(doorsLayers(0).left, -0)
  assert.equal(doorsLayers(1).left, -760)
  assert.equal(doorsLayers(1).right, 1480)
  near(doorsLayers(0.25).left, -167.2, 0.01)
  assert.equal(doorsLayers(0.5).copy, 0)
  assert.equal(doorsLayers(0.75).copy, 1)
  assert.equal(doorsLayers(1).shade, 0)
})

test('S05 overhead lands at (-80, 0, 1600x900); the sign only at KF100', () => {
  nearRect(floorLayers(1).overhead, [-80, 0, 1600, 900], 0.01)
  assert.equal(floorLayers(0.5).interiorOpacity, 0)
  assert.equal(floorLayers(0.75).sign, 0)
  assert.equal(floorLayers(1).sign, 1)
})

test('steps swap at the midpoint between keyframes; scenes crossfade at boundaries', () => {
  assert.deepEqual([0, 0.12, 0.13, 0.5, 0.87, 0.88, 1].map(step), [0, 0, 1, 2, 3, 4, 4])
  assert.equal(sceneOpacity(0.1, 0), 1)
  assert.equal(sceneOpacity(0.1, 1), 0)
  near(sceneOpacity(0.2, 0), 1 / 1, 1e-9)
  near(sceneOpacity(0.2, 1), 1, 1e-9)
  near(sceneOpacity(0.1875, 1), 0.5, 1e-9)
  assert.equal(sceneOpacity(0.2, 1, 0), 1)
})

test('snap points: every keyframe of every scene, shared boundaries once', () => {
  const p = snapPoints()
  assert.equal(p.length, 21)
  assert.equal(p[0], 0)
  assert.equal(p.at(-1), 1)
  assert.ok(p.includes(0.6625))
})
