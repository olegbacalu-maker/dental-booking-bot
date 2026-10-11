import { describe, expect, it } from 'vitest'
import { fitRadius, type Bounds } from './fit'
import { labelsFor, VIEWS, type ViewName } from './scene'

/* Сама сцена (WebGL) тестами не покрыта — здесь её чистые правила: углы видов и
   слой номеров по виду. Радиус вида считает `fit.ts` (свои тесты); здесь только
   то, что для углов каждого вида и габарита дуги он попадает в пределы колеса. */
const rad = (d: number): number => (d * Math.PI) / 180
const ARCH: Bounds = { min: [-36, -30, -58], max: [36, 30, 4] }

describe('scene: правила видов', () => {
  it('номера сами включаются на окклюзионных видах и только там', () => {
    const on = (Object.keys(VIEWS) as ViewName[]).filter(labelsFor)
    expect(on.sort()).toEqual(['jos', 'sus'])
    expect(labelsFor('frontal')).toBe(false)
  })

  it('у видов только углы — дистанции нет, её даёт подгонка под окно в пределах колеса', () => {
    for (const [name, v] of Object.entries(VIEWS)) {
      expect(v).toHaveLength(2)
      for (const aspect of [0.7, 1.08, 2.2]) {
        const r = fitRadius(ARCH, [0, 0, -16], rad(v[0]), rad(v[1]), 30, aspect)
        expect(r, `${name} @${aspect}`).toBeGreaterThan(70)
        expect(r, `${name} @${aspect}`).toBeLessThan(420)
      }
    }
  })
})
