import { describe, expect, it } from 'vitest'
import { COLOR, effState, FINISH, finishFor, finishOf, hex, lerpHex, mixFinish, sameFinish, sameLook, setFinish, setTransparent, structChanged, targetLook, type Finish, type Look } from './look'

/* Вид зуба — таблица состояний → видимость и цвета, с палитрой сервера. */

const PALETTE = { ok: '#1F2937', carie: '#EF4444', obturatie: '#3B82F6', coroana: '#F59E0B', implant: '#8B5CF6', extras: '#64748B', lipsa: '#CBD5E1' }
const tooth = (state: string, sfst: Record<string, string> = {}, mk: string[] = [], bridge: { role: string; material: string } | null = null) =>
  ({ state, sfst, mk, bridge })

describe('цвета', () => {
  it('hex читает #RRGGBB, прочее — 0; lerp по компонентам', () => {
    expect(hex('#EF4444')).toBe(0xef4444)
    expect(hex(' ef4444 ')).toBe(0xef4444)
    expect(hex('red')).toBe(0)
    expect(lerpHex(0x000000, 0xffffff, 0.5)).toBe(0x808080)
    expect(lerpHex(0x102030, 0x102030, 0.7)).toBe(0x102030)
    expect(lerpHex(0x000000, 0xffffff, 2)).toBe(0xffffff)
  })
})

describe('эффективное состояние', () => {
  it('поверхность с кариесом красит «здоровый» зуб; у коронки поверхности не считаются', () => {
    expect(effState(tooth('ok'))).toBe('ok')
    expect(effState(tooth('ok', { O: 'obturatie' }))).toBe('obturatie')
    expect(effState(tooth('ok', { O: 'obturatie', M: 'carie' }))).toBe('carie')
    expect(effState(tooth('coroana', { O: 'carie' }))).toBe('coroana')
    expect(effState(tooth('implant'))).toBe('implant')
  })
})

describe('вид по состоянию', () => {
  it('здоровый: эмаль везде, коронка и корни видны, ни винта, ни лунки', () => {
    const l = targetLook(tooth('ok'), PALETTE)
    expect(l.cols).toEqual([COLOR.enamel, COLOR.enamel, COLOR.enamel, COLOR.enamel, COLOR.enamel])
    expect([l.crown, l.roots, l.screw, l.socket, l.ghost, l.mark]).toEqual([true, true, false, false, false, false])
    expect(l.opacity).toBe(1)
    expect(l.fin).toEqual([FINISH.enamel, FINISH.enamel, FINISH.enamel, FINISH.enamel, FINISH.enamel])
  })

  it('кариес на поверхности O красит только её цветом палитры (0.6), остальные — эмаль', () => {
    const l = targetLook(tooth('ok', { O: 'carie' }), PALETTE)
    expect(l.st).toBe('carie')
    expect(l.cols[0]).toBe(lerpHex(COLOR.enamel, 0xef4444, 0.6))
    expect(l.cols.slice(1)).toEqual([COLOR.enamel, COLOR.enamel, COLOR.enamel, COLOR.enamel])
  })

  it('кариес зуба целиком без поверхностей — лёгкий оттенок (0.32) на всех пяти', () => {
    const l = targetLook(tooth('carie'), PALETTE)
    const c = lerpHex(COLOR.enamel, 0xef4444, 0.32)
    expect(l.cols).toEqual([c, c, c, c, c])
  })

  it('имплант: винт есть, корней нет, коронка керамическая', () => {
    const l = targetLook(tooth('implant'), PALETTE)
    expect([l.screw, l.roots, l.crown, l.implant]).toEqual([true, false, true, true])
    expect(l.cols[0]).toBe(COLOR.ceramic)
    expect(l.fin.every((f) => f === FINISH.zirconia)).toBe(true)
  })

  it('имплантат без коронки (30.10): винт и формирователь, ни коронки, ни корней; готовый имплант формирователя не имеет', () => {
    const l = targetLook(tooth('implant_fc'), PALETTE)
    expect([l.screw, l.cap, l.roots, l.crown, l.implant]).toEqual([true, true, false, false, false])
    expect(targetLook(tooth('implant'), PALETTE).cap).toBe(false)
    expect(structChanged(l, targetLook(tooth('implant'), PALETTE))).toBe(true)
  })

  it('коронка и тело моста — золото без корней у тела; опора моста корни оставляет', () => {
    const crown = targetLook(tooth('coroana'), PALETTE)
    expect([crown.gold, crown.roots, crown.fin[0]]).toEqual([true, true, FINISH.crown])
    const pontic = targetLook(tooth('lipsa', {}, [], { role: 'corp', material: 'zirconiu' }), PALETTE)
    expect([pontic.gold, pontic.pontic, pontic.roots, pontic.ghost]).toEqual([true, true, false, false])
    const abutment = targetLook(tooth('ok', {}, [], { role: 'stalp', material: 'zirconiu' }), PALETTE)
    expect([abutment.gold, abutment.roots]).toEqual([false, true])
  })

  it('⭐ отсутствующий — пустое место с пунктиром шейки, БЕЗ коронки (26.09: призрак 0,22 читался целым зубом); удалённый — лунка', () => {
    const ghost = targetLook(tooth('lipsa'), PALETTE)
    expect([ghost.ghost, ghost.gap, ghost.crown, ghost.roots, ghost.socket]).toEqual([true, true, false, false, false])
    const gone = targetLook(tooth('extras'), PALETTE)
    expect([gone.gone, gone.crown, gone.socket, gone.roots, gone.gap]).toEqual([true, false, true, false, false])
    // тело моста на отсутствующем — золото, не пустое место
    const pontic = targetLook(tooth('lipsa', {}, [], { role: 'corp', material: 'zr' }), PALETTE)
    expect([pontic.gap, pontic.crown]).toEqual([false, true])
    expect(targetLook(tooth('ok'), PALETTE).gap).toBe(false)
  })

  it('отметка «în tratament» — кольцо; пустая палитра не роняет, а даёт чёрный оттенок', () => {
    expect(targetLook(tooth('ok', {}, ['tratament']), PALETTE).mark).toBe(true)
    expect(targetLook(tooth('ok', {}, ['tratament']), PALETTE).devital).toBe(false)
    // «nerv extras» живёт ПОВЕРХ коронки — ради этого отметка, а не состояние
    expect(targetLook(tooth('coroana', {}, ['devital']), PALETTE).devital).toBe(true)
    expect(targetLook(tooth('coroana', {}, ['devital']), PALETTE).gold).toBe(true)
    const l = targetLook(tooth('carie'), {})
    expect(l.cols[0]).toBe(lerpHex(COLOR.enamel, 0, 0.32))
  })

  it('сцена смены состояния нужна при смене состояния или роли тела моста, не при перекраске поверхности', () => {
    const a = targetLook(tooth('ok'), PALETTE)
    const b = targetLook(tooth('ok', { O: 'obturatie' }), PALETTE)
    const c = targetLook(tooth('ok', { O: 'carie' }), PALETTE)
    expect(structChanged(null, a)).toBe(false)
    expect(structChanged(a, b)).toBe(true)
    expect(structChanged(b, c)).toBe(true)
    expect(structChanged(c, targetLook(tooth('ok', { M: 'carie' }), PALETTE))).toBe(false)
  })
})

describe('прозрачность материала', () => {
  it('⭐ смена transparent просит пересборку программы (OPAQUE в шейдере three r151+), повтор того же значения — нет', () => {
    const m = { transparent: false, needsUpdate: false }
    setTransparent(m, true)
    expect(m).toEqual({ transparent: true, needsUpdate: true })
    m.needsUpdate = false
    setTransparent(m, true)
    expect(m.needsUpdate).toBe(false)
    setTransparent(m, false)
    expect(m).toEqual({ transparent: false, needsUpdate: true })
  })
})

/* Тот же вид — `paint` не трогает зуб, и идущая сцена смены состояния доживает до
   своего `applyLook(…, true)`. Любое поле, которое ставит `applyLook`, обязано
   отличать вид: иначе настоящая смена молча не применится. */
describe('тот же вид', () => {
  // сдвинуть значение любого вида: флаг — наоборот, число — на 1, строку — дописать,
  // массив и объект — их первый элемент
  const bump = (v: unknown): unknown => {
    if (typeof v === 'boolean') return !v
    if (typeof v === 'number') return v + 1
    if (typeof v === 'string') return v + '_'
    if (Array.isArray(v)) return [bump(v[0]), ...v.slice(1)]
    if (v && typeof v === 'object') {
      const k = Object.keys(v)[0] ?? ''
      return { ...v, [k]: bump((v as Record<string, unknown>)[k]) }
    }
    return v
  }

  it('два расчёта одних данных — тот же вид; пустой прежний — не тот же', () => {
    const t = tooth('ok', { O: 'carie', M: 'obturatie' }, ['devital'])
    expect(sameLook(targetLook(t, PALETTE), targetLook(t, PALETTE))).toBe(true)
    expect(sameLook(null, targetLook(t, PALETTE))).toBe(false)
  })

  it('⭐ смена КАЖДОГО поля по отдельности — уже не тот же вид (список полей берётся из самого вида)', () => {
    const base = targetLook(tooth('ok', { O: 'carie' }, ['tratament']), PALETTE)
    const keys = Object.keys(base) as (keyof Look)[]
    expect(keys.length).toBeGreaterThan(10)
    for (const k of keys) {
      const other = { ...base, [k]: bump(base[k]) } as Look
      expect(sameLook(base, other), String(k)).toBe(false)
    }
  })

  it('гашение, призрак и пародонт — разные виды', () => {
    const base = targetLook(tooth('ok', { O: 'carie' }), PALETTE)
    expect(sameLook(base, { ...base, opacity: 0.16 })).toBe(false)
    expect(sameLook(targetLook(tooth('ok'), PALETTE), targetLook(tooth('lipsa'), PALETTE))).toBe(false)
    expect(sameLook(base, { ...base, cols: base.cols.map(() => COLOR.enamel) })).toBe(false)
  })
})

/* Вид «Simplu» (прототип 19.10, в продукте с 24.10): отделка поверхности по
   смыслу — блеск, лак, шероховатость. Цвет остаётся за палитрой сервера. */
describe('отделка по смыслу', () => {
  it('у поверхности с находкой — своя отделка (порядок SURF: O V L M D), остальные — эмаль', () => {
    const l = targetLook(tooth('ok', { O: 'carie', M: 'obturatie', D: 'obturatie' }), PALETTE)
    expect(l.fin).toEqual([FINISH.caries, FINISH.enamel, FINISH.enamel, FINISH.fill, FINISH.fill])
  })

  it('находка зуба целиком без поверхностей — на всех пяти, как оттенок цвета', () => {
    expect(targetLook(tooth('carie'), PALETTE).fin.every((f) => f === FINISH.caries)).toBe(true)
    expect(targetLook(tooth('obturatie'), PALETTE).fin.every((f) => f === FINISH.fill)).toBe(true)
  })

  it('коронка и тело моста — металлокерамика целиком (поверхности под коронкой не считаются); имплант — цирконий', () => {
    expect(targetLook(tooth('coroana', { O: 'carie' }), PALETTE).fin.every((f) => f === FINISH.crown)).toBe(true)
    const pontic = targetLook(tooth('lipsa', {}, [], { role: 'corp', material: 'zirconiu' }), PALETTE)
    expect(pontic.fin.every((f) => f === FINISH.crown)).toBe(true)
    expect(finishFor(false, true, 'carie')).toBe(FINISH.zirconia)
    expect(finishFor(false, false, undefined)).toBe(FINISH.enamel)
  })

  it('⭐ отделка не трогает цвет: цвета поверхностей те же, что у палитры сервера', () => {
    const l = targetLook(tooth('ok', { O: 'carie' }), PALETTE)
    expect(l.cols[0]).toBe(lerpHex(COLOR.enamel, 0xef4444, 0.6))
    for (const f of Object.values(FINISH)) {
      // `natural` — доля живой эмали (край, линия эмаль–цемент, `enamel.ts`), тоже не цвет
      expect(Object.keys(f).sort()).toEqual(['clearcoat', 'clearcoatRoughness', 'ior', 'metalness', 'natural', 'roughness', 'sheen', 'specularIntensity'])
    }
  })

  it('смысл таблицы: мел матовее эмали, композит глаже; цирконий преломляет сильнее эмали; титан — металл', () => {
    expect(FINISH.caries.roughness).toBeGreaterThan(FINISH.enamel.roughness)
    expect(FINISH.enamel.roughness).toBeGreaterThan(FINISH.fill.roughness)
    expect(FINISH.caries.clearcoat).toBeLessThan(FINISH.enamel.clearcoat)
    expect(FINISH.zirconia.ior).toBeGreaterThan(FINISH.enamel.ior)
    expect([FINISH.enamel.ior, FINISH.zirconia.ior]).toEqual([1.62, 2.15])
    expect(FINISH.titanium.metalness).toBe(1)
    expect(FINISH.crown.metalness).toBeGreaterThan(0)
  })

  it('твин отделки: концы, середина, выход за [0, 1] прижат', () => {
    const a = FINISH.enamel
    const b = FINISH.fill
    expect(sameFinish(mixFinish(a, b, 0), a)).toBe(true)
    expect(sameFinish(mixFinish(a, b, 1), b)).toBe(true)
    expect(mixFinish(a, b, 0.5).roughness).toBeCloseTo((a.roughness + b.roughness) / 2)
    expect(sameFinish(mixFinish(a, b, 3), b)).toBe(true)
    expect(sameFinish(a, b)).toBe(false)
    // конец твина — ровно цель, без хвоста в последнем знаке (кариес → коронка: 0.6 + (0.04 − 0.6))
    expect(sameFinish(mixFinish(FINISH.caries, FINISH.crown, 1), FINISH.crown)).toBe(true)
  })

  it('setFinish ставит только семь полей отделки: цвет и прозрачность материала не трогаются; finishOf — копия', () => {
    const m: Finish & { color: number; opacity: number; transparent: boolean } = { ...FINISH.enamel, color: 0x123456, opacity: 0.16, transparent: true }
    setFinish(m, FINISH.crown)
    expect(sameFinish(m, FINISH.crown)).toBe(true)
    expect([m.color, m.opacity, m.transparent]).toEqual([0x123456, 0.16, true])
    const c = finishOf(m)
    m.roughness = 0.9
    expect(c.roughness).toBe(FINISH.crown.roughness)
    expect('color' in c).toBe(false)
  })
})
