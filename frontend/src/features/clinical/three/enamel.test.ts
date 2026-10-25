import { ShaderLib } from 'three'
import { describe, expect, it } from 'vitest'
import { CEJ_RISE, cejHeight, edgeStrength, enamelColors, HOOKS, patchEnamelShader } from './enamel'
import { anchorsFor, marginH } from './gum'
import { COLOR, FINISH, finishFor, physOf } from './look'
import type { Cls } from './toothGeometry'

/* Живая эмаль (25.10): края и линию эмаль–цемент рисует шейдер, проверить его
   кадром может только стенд — здесь числа и сам патч строк шейдера. */
const CLS: Cls[] = ['incisor_c', 'incisor_l', 'canine', 'premolar', 'molar']
const rad = (d: number): number => (d * Math.PI) / 180

describe('enamel: патч шейдера', () => {
  it('⛔ каждая точка подмены есть в шейдере MeshPhysicalMaterial этой версии three', () => {
    // не нашлась — `replace` молча ничего не делает: ни края, ни линии, ни ошибки
    const p = patchEnamelShader(ShaderLib.physical.vertexShader, ShaderLib.physical.fragmentShader)
    expect(p.missing).toEqual([])
    expect(p.vs).toContain('vDpTooth = position;')
    expect(p.fs).toContain('DP_CEMENT')
    expect(p.fs).toContain('roughnessFactor = mix(roughnessFactor')
    expect(p.fs).toContain('material.clearcoat = mix(material.clearcoat')
  })

  it('пропажу точки подмены патч называет, а не глотает', () => {
    const p = patchEnamelShader('void main() {}', 'void main() {}')
    expect(p.missing.sort()).toEqual(Object.keys(HOOKS).sort())
  })

  it('отделка ниже линии — та же, что у корня (FINISH.dentin)', () => {
    const p = patchEnamelShader(ShaderLib.physical.vertexShader, ShaderLib.physical.fragmentShader)
    expect(p.fs).toContain(`mix(roughnessFactor, ${FINISH.dentin.roughness}, dpCe)`)
    expect(p.fs).toContain(`mix(material.clearcoat, ${FINISH.dentin.clearcoat.toFixed(1)}, dpCe)`)
  })
})

describe('enamel: линия эмаль–цемент', () => {
  it('⛔ у здоровой десны линия всюду ниже края: цемент виден только при рецессии', () => {
    for (const cls of CLS) {
      const anchors = anchorsFor(cls, null, false, false)
      for (let i = 0; i < 360; i++) {
        const th = rad(i)
        const gap = marginH(anchors, th) - cejHeight(cls, th)
        expect(gap, `${cls} @${i}°`).toBeGreaterThan(0.3)
      }
    }
  })

  it('волной: на губной и язычной стороне — на шейке, на контактных выше', () => {
    for (const cls of CLS) {
      expect(cejHeight(cls, rad(90))).toBeCloseTo(0, 6)
      expect(cejHeight(cls, rad(270))).toBeCloseTo(0, 6)
      expect(cejHeight(cls, 0)).toBeCloseTo(CEJ_RISE[cls], 6)
      expect(cejHeight(cls, Math.PI)).toBeCloseTo(CEJ_RISE[cls], 6)
      expect(cejHeight(cls, rad(45))).toBeLessThan(CEJ_RISE[cls])
    }
  })

  it('у резца волна выше, чем у моляра (учебник: 3–3,5 против ~0,5–1 мм)', () => {
    expect(CEJ_RISE.incisor_c).toBeGreaterThan(CEJ_RISE.canine)
    expect(CEJ_RISE.canine).toBeGreaterThan(CEJ_RISE.premolar)
    expect(CEJ_RISE.premolar).toBeGreaterThan(CEJ_RISE.molar)
  })

  it('тон ниже линии — дентин корня: эмаль × множитель = цвет корня', () => {
    const lin = (c: number): number => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
    const ch = (h: number, s: number): number => lin(((h >> s) & 0xff) / 255)
    const { cement } = enamelColors()
    ;[16, 8, 0].forEach((s, i) => {
      expect(ch(COLOR.enamel, s) * (cement[i] ?? 0)).toBeCloseTo(ch(COLOR.dentin, s), 6)
    })
  })
})

describe('enamel: режущий край', () => {
  it('край — у резцов и клыка, у жевательных нет; у нижних слабее', () => {
    expect(edgeStrength('premolar', true)).toBe(0)
    expect(edgeStrength('molar', false)).toBe(0)
    expect(edgeStrength('incisor_c', true)).toBeGreaterThan(edgeStrength('incisor_l', true))
    expect(edgeStrength('incisor_l', true)).toBeGreaterThan(edgeStrength('canine', true))
    expect(edgeStrength('canine', true)).toBeGreaterThan(0)
    for (const cls of CLS) expect(edgeStrength(cls, false)).toBeLessThanOrEqual(edgeStrength(cls, true))
  })

  it('зона края темнее эмали и голубее, ободок светлее зоны', () => {
    const { trans, halo } = enamelColors()
    const [r = 0, g = 0, b = 0] = trans
    expect(b / r).toBeGreaterThan(1)
    expect(halo.every((v, i) => v > (trans[i] ?? 1))).toBe(true)
    expect(g).toBeGreaterThan(0)
  })
})

describe('enamel: только живая эмаль', () => {
  it('⛔ natural = 1 только у эмали: пломба, кариес, коронка, цирконий цвета не теряют', () => {
    expect(FINISH.enamel.natural).toBe(1)
    for (const [k, f] of Object.entries(FINISH)) {
      if (k !== 'enamel') expect(f.natural, k).toBe(0)
    }
    expect(finishFor(false, false, undefined).natural).toBe(1)
    expect(finishFor(false, false, 'carie').natural).toBe(0)
    expect(finishFor(false, false, 'obturatie').natural).toBe(0)
    expect(finishFor(true, false, undefined).natural).toBe(0)
    expect(finishFor(false, true, undefined).natural).toBe(0)
  })

  it('в конструктор материала отделка идёт без natural (three отверг бы поле предупреждением)', () => {
    for (const f of Object.values(FINISH)) expect(Object.keys(physOf(f))).not.toContain('natural')
  })
})
