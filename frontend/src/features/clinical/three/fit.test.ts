import { describe, expect, it } from 'vitest'
import { corners, EMPTY_BOUNDS, FILL, fillAt, fitRadius, isEmpty, union, type Bounds } from './fit'
import type { Vec3 } from './arch'

const rad = (d: number): number => (d * Math.PI) / 180
const HOME: Vec3 = [0, 0, -16]
/* порядок величин дуги сцены: ±36 по x, ±30 по y, глубина до −58 по z */
const ARCH: Bounds = { min: [-36, -30, -58], max: [36, 30, 4] }
const FOV = 30

describe('fit: камера под окно', () => {
  it('у подобранного радиуса ограничивающая ось занимает ровно FILL, другая — не больше', () => {
    for (const aspect of [0.6, 1.08, 1.4, 2.2]) {
      const r = fitRadius(ARCH, HOME, 0, rad(80), FOV, aspect)
      const f = fillAt(ARCH, HOME, 0, rad(80), FOV, aspect, r)
      expect(Math.max(f.w, f.h)).toBeCloseTo(FILL, 9)
      expect(f.w).toBeLessThanOrEqual(FILL + 1e-9)
      expect(f.h).toBeLessThanOrEqual(FILL + 1e-9)
    }
  })

  it('узкое окно ограничивает шириной, широкое — высотой; шире окно — не дальше камера', () => {
    const narrow = fitRadius(ARCH, HOME, 0, rad(80), FOV, 0.6)
    const wide = fitRadius(ARCH, HOME, 0, rad(80), FOV, 2.2)
    expect(narrow).toBeGreaterThan(wide)
    const fn = fillAt(ARCH, HOME, 0, rad(80), FOV, 0.6, narrow)
    expect(fn.w).toBeCloseTo(FILL, 9)
    expect(fn.h).toBeLessThan(FILL)
    const fw = fillAt(ARCH, HOME, 0, rad(80), FOV, 2.2, wide)
    expect(fw.h).toBeCloseTo(FILL, 9)
    expect(fw.w).toBeLessThan(FILL)
    let prev = Infinity
    for (const a of [0.5, 0.8, 1, 1.3, 1.8, 2.5]) {
      const r = fitRadius(ARCH, HOME, 0, rad(80), FOV, a)
      expect(r).toBeLessThanOrEqual(prev + 1e-9)
      prev = r
    }
  })

  it('дальше камера — меньше доля; радиус зеркален по азимуту и не зависит от знака высоты', () => {
    const r = fitRadius(ARCH, HOME, rad(-62), rad(82), FOV, 1.4)
    expect(fitRadius(ARCH, HOME, rad(62), rad(82), FOV, 1.4)).toBeCloseTo(r, 9)
    const far = fillAt(ARCH, HOME, rad(-62), rad(82), FOV, 1.4, r * 1.5)
    expect(Math.max(far.w, far.h)).toBeLessThan(FILL)
    // габарит симметричен по y — взгляд чуть сверху и чуть снизу дают один радиус
    expect(fitRadius(ARCH, HOME, 0, rad(80), FOV, 1.4)).toBeCloseTo(fitRadius(ARCH, HOME, 0, rad(100), FOV, 1.4), 6)
  })

  it('вид сверху и снизу (окклюзионные): кадр ограничивает глубина дуги, не её высота', () => {
    const flat: Bounds = { min: [-36, 0, -58], max: [36, 0, 4] }
    const tall: Bounds = { min: [-36, -30, -58], max: [36, 30, 4] }
    // почти точно сверху: высота параллелепипеда идёт вдоль взгляда — радиус
    // растёт не больше чем на эту высоту плюс её малую проекцию поперёк
    const a = fitRadius(flat, HOME, 0, rad(5), FOV, 1.4)
    const b = fitRadius(tall, HOME, 0, rad(5), FOV, 1.4)
    expect(b - a).toBeLessThanOrEqual(30 + (30 * Math.sin(rad(5))) / (FILL * Math.tan(rad(15))) + 1e-6)
    expect(b).toBeGreaterThan(a)
    // камера строго над целью — базис не вырождается, ответ конечен
    const top = fitRadius(tall, HOME, 0, 0, FOV, 1.4)
    expect(Number.isFinite(top)).toBe(true)
    expect(top).toBeGreaterThan(0)
  })

  it('пустой габарит — радиус 0 и доля 0; объединение и углы', () => {
    expect(isEmpty(EMPTY_BOUNDS)).toBe(true)
    expect(fitRadius(EMPTY_BOUNDS, HOME, 0, rad(80), FOV, 1.4)).toBe(0)
    expect(fillAt(EMPTY_BOUNDS, HOME, 0, rad(80), FOV, 1.4, 100)).toEqual({ w: 0, h: 0 })
    const u = union(union(EMPTY_BOUNDS, { min: [-1, 0, -2], max: [1, 1, 0] }), { min: [0, -3, -1], max: [5, 0, 7] })
    expect(u).toEqual({ min: [-1, -3, -2], max: [5, 1, 7] })
    expect(isEmpty(u)).toBe(false)
    expect(corners(u)).toHaveLength(8)
    expect(corners(u)).toContainEqual([5, -3, 7])
  })

  it('глубина за камерой — доля бесконечна (камера внутри габарита)', () => {
    const f = fillAt(ARCH, HOME, 0, rad(80), FOV, 1.4, 5)
    expect(f.w).toBe(Infinity)
  })
})
