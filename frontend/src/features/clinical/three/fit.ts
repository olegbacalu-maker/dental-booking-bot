import type { Vec3 } from './arch'

/* Камера под окно (11.10): дистанция вида не зашита числом на каждый вид, а
   считается так, чтобы габарит дуги занимал долю `FILL` кадра по той оси,
   которая ограничивает первой — в узком окне это ширина, на широком мониторе
   при сцене фиксированной высоты — высота. Здесь только числа: сцена даёт
   параллелепипед видимых челюстей (в своих мм), угол и отношение сторон
   камеры; обратно идёт радиус орбиты. Колесо, щипок и зум «−/+» работают от
   этого радиуса как от базы, фокус на зубе (`focus.ts`) — своя дистанция. */

export interface Bounds { min: Vec3; max: Vec3 }

/** Доля кадра под габарит дуги по ограничивающей оси. Габарит — прямоугольный
 *  параллелепипед вокруг коронок и всего тела десны, он заметно шире силуэта
 *  (углы коробки пусты, десна к низу сужается): 0,9 коробки — это ≈ 0,8
 *  самой дуги на кадре. 0,8 коробки ставило камеру ДАЛЬШЕ прежних 172 мм
 *  (185 во фронтальном виде) — дуга становилась мельче, чем была. */
export const FILL = 0.9

export const EMPTY_BOUNDS: Bounds = {
  min: [Infinity, Infinity, Infinity],
  max: [-Infinity, -Infinity, -Infinity],
}

export const isEmpty = (b: Bounds): boolean => b.min[0] > b.max[0]

export function union(a: Bounds, b: Bounds): Bounds {
  return {
    min: [Math.min(a.min[0], b.min[0]), Math.min(a.min[1], b.min[1]), Math.min(a.min[2], b.min[2])],
    max: [Math.max(a.max[0], b.max[0]), Math.max(a.max[1], b.max[1]), Math.max(a.max[2], b.max[2])],
  }
}

/** Восемь углов параллелепипеда. */
export function corners(b: Bounds): Vec3[] {
  const out: Vec3[] = []
  for (const x of [b.min[0], b.max[0]]) for (const y of [b.min[1], b.max[1]]) for (const z of [b.min[2], b.max[2]]) out.push([x, y, z])
  return out
}

interface Frame {
  /** направление от цели к камере */
  d: Vec3
  right: Vec3
  up: Vec3
  tanV: number
  tanH: number
}

/** Базис камеры, которая смотрит в цель с направления (theta, phi) — то же, что
 *  `applyCam` сцены и `Matrix4.lookAt` с up = (0, 1, 0). */
function frame(theta: number, phi: number, fovDeg: number, aspect: number): Frame {
  const sp = Math.sin(phi)
  const d: Vec3 = [sp * Math.sin(theta), Math.cos(phi), sp * Math.cos(theta)]
  // right = up × d; камера строго над целью (sin φ = 0) — ось x мира
  const rl = Math.hypot(d[2], d[0])
  const right: Vec3 = rl < 1e-6 ? [1, 0, 0] : [d[2] / rl, 0, -d[0] / rl]
  const up: Vec3 = [
    d[1] * right[2] - d[2] * right[1],
    d[2] * right[0] - d[0] * right[2],
    d[0] * right[1] - d[1] * right[0],
  ]
  const tanV = Math.tan((fovDeg * Math.PI) / 360)
  return { d, right, up, tanV, tanH: tanV * aspect }
}

const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

/**
 * Радиус орбиты, при котором `box` целиком в кадре и его проекция занимает не
 * больше `fill` ширины и высоты кадра. Камера смотрит в `target` с направления
 * сферических углов (`theta` — азимут, `phi` — от оси y), `fovDeg` —
 * вертикальный угол камеры, `aspect` — ширина/высота кадра.
 *
 * Угол параллелепипеда виден, если его смещение вверх (вбок) в камере не
 * больше `fill` · глубина · tg(угол/2), а глубина = радиус − проекция на
 * направление к камере; отсюда нижняя граница радиуса для каждого угла по
 * каждой оси, ответ — наибольшая. Пустой габарит — 0.
 */
export function fitRadius(box: Bounds, target: Vec3, theta: number, phi: number, fovDeg: number, aspect: number, fill = FILL): number {
  if (isEmpty(box)) return 0
  const f = frame(theta, phi, fovDeg, aspect)
  let r = 0
  for (const c of corners(box)) {
    const rel: Vec3 = [c[0] - target[0], c[1] - target[1], c[2] - target[2]]
    const along = dot(rel, f.d)
    const dx = Math.abs(dot(rel, f.right))
    const dy = Math.abs(dot(rel, f.up))
    r = Math.max(r, along + dy / (fill * f.tanV), along + dx / (fill * f.tanH))
  }
  return r
}

/** Какую долю кадра по ширине и высоте занимает проекция `box` при радиусе
 *  `r` — для стендов и проверок: у радиуса `fitRadius` ограничивающая ось
 *  даёт ровно `fill`, другая — меньше. */
export function fillAt(box: Bounds, target: Vec3, theta: number, phi: number, fovDeg: number, aspect: number, r: number): { w: number; h: number } {
  if (isEmpty(box)) return { w: 0, h: 0 }
  const f = frame(theta, phi, fovDeg, aspect)
  let w = 0
  let h = 0
  for (const c of corners(box)) {
    const rel: Vec3 = [c[0] - target[0], c[1] - target[1], c[2] - target[2]]
    const depth = r - dot(rel, f.d)
    if (depth <= 0) return { w: Infinity, h: Infinity }
    w = Math.max(w, Math.abs(dot(rel, f.right)) / (depth * f.tanH))
    h = Math.max(h, Math.abs(dot(rel, f.up)) / (depth * f.tanV))
  }
  return { w, h }
}
