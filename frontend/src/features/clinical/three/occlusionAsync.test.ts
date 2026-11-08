import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildJaw, GEOM, LOWER, shapesOf, UPPER } from '../../../test/jaws'
import { GAP, GAP_CLOSED, layoutArch } from './arch'
import { anchorsFor, archFrame, buildGum, stripesFor, vertexNormals, type GumTooth } from './gum'
import { toCls } from './toothGeometry'
import { packed, peekPlan, planKey, requestGumShape, requestPlan, resetOcclusionAsync, sendGum, shapesPrint, type Reply } from './occlusionAsync'
import { gumStore, gumTarget, type GumIn } from './occlusionGum'
import { occlusionPlan, ZERO_TEETH } from './occlusionPlan'

/* План прикуса вне главного потока (координатор 08.11): воркер считает ТЕМИ ЖЕ функциями,
   кэш — модуля (повторное открытие вкладки мгновенно), опоздавший ответ не путается.
   В jsdom воркера нет — запасной путь (тот же расчёт, отложенно); протокол самого воркера
   проверяется его обработчиком с подменённым `self`. */

const SLOW = { timeout: 30000 }
const C = (GAP - GAP_CLOSED) / 2
const S = shapesOf(buildJaw(UPPER, true), buildJaw(LOWER, false))
const ALL = new Set(S.keys())
const OLEG = { angle_dr: 'II/1', angle_st: 'III', incrucisata: '13-43', deschisa: '12-22' }

/** Нижняя десна, как строит сцена (`buildGum` по зубам раскладки, как `gumWarp.test`), и её рамка. */
const LOW = buildJaw(LOWER, false)
function gumIn(): GumIn {
  const lay = layoutArch(LOWER.map((n) => ({ n, md: GEOM.L[n % 10]!.md })), false)
  const gt: GumTooth[] = LOWER.map((n) => {
    const b = LOW.get(n)!
    const g = GEOM.L[n % 10]!
    return {
      n, kind: 'tooth', s: b.p.s, md: g.md, bl: g.bl, root: 12, position: b.p.position, xAxis: b.p.xAxis, yAxis: b.p.yAxis, zAxis: b.p.zAxis,
      surf: b.cm.surf, anchors: anchorsFor(toCls(g.cls), null, false, false), stripe: stripesFor(null),
    }
  })
  const raw = buildGum({ A: lay.A, D: lay.D, apex: lay.apex, yBase: lay.yBase, occ: 1, teeth: gt })
  const F = archFrame(lay.A, lay.D, lay.apex)
  const teeth = LOWER.map((n) => {
    const p = S.get(n)!.place
    return { n, u: F.project(p.position[0], p.position[2], p.s), neckY: p.position[1], x: p.position[0], z: p.position[2] }
  })
  return { positions: Float32Array.from(raw.positions), index: Uint32Array.from(raw.index), A: lay.A, D: lay.D, apex: lay.apex, teeth, occ: 1 }
}

afterEach(() => {
  resetOcclusionAsync()
  vi.unstubAllGlobals()
})

describe('план прикуса без главного потока (`occlusionAsync`)', () => {
  it('⭐ отпечаток раскладки: тот же для той же раскладки, другой — при другом месте зуба', () => {
    const fp = shapesPrint(S)
    expect(shapesPrint(new Map(S))).toBe(fp)
    const moved = new Map(S)
    const s11 = S.get(11)!
    moved.set(11, { ...s11, place: { ...s11.place, position: [s11.place.position[0] + 0.01, s11.place.position[1], s11.place.position[2]] } })
    expect(shapesPrint(moved)).not.toBe(fp)
  })

  it('⭐ без воркера: план тот же, что на месте; повтор — из кэша модуля тем же объектом; два запроса — один расчёт', SLOW, async () => {
    const fp = shapesPrint(S)
    const key = planKey(fp, C, OLEG, [])
    expect(peekPlan(key)).toBeUndefined()
    const a = requestPlan(S, fp, C, OLEG, ALL, key)
    const b = requestPlan(S, fp, C, OLEG, ALL, key)
    expect(b).toBe(a)
    const plan = await a
    expect(plan).toEqual(occlusionPlan(OLEG, S, C, ALL))
    expect(peekPlan(key)).toBe(plan)
    expect(await requestPlan(S, fp, C, OLEG, ALL, key)).toBe(plan)
  })

  it('ключ различает запись и скрытые зубы', () => {
    const fp = shapesPrint(S)
    expect(planKey(fp, C, OLEG, [])).not.toBe(planKey(fp, C, { ...OLEG, deschisa: '' }, []))
    expect(planKey(fp, C, OLEG, [])).not.toBe(planKey(fp, C, OLEG, [47]))
  })

  it('⭐ воркер (обработчик с подменённым self): сетки один раз, план равен плану на месте, форма десны — та же', SLOW, async () => {
    const out: Reply[] = []
    const fake: { onmessage: ((ev: { data: unknown }) => void) | null; postMessage: (m: Reply) => void } = {
      onmessage: null,
      postMessage: (m) => { out.push(m) },
    }
    vi.stubGlobal('self', fake)
    vi.resetModules()
    await import('./occlusionWorker')
    expect(fake.onmessage).toBeTypeOf('function')
    const fp = shapesPrint(S)
    fake.onmessage!({ data: { t: 'shapes', fp, shapes: packed(S) } })
    fake.onmessage!({ data: { t: 'plan', id: 7, fp, rec: OLEG, closeY: C, shown: [...ALL] } })
    const r = out[0]!
    expect(r.t).toBe('plan')
    if (r.t !== 'plan') return
    expect(r.id).toBe(7)
    expect(r.missing).toBe(false)
    expect(r.plan).toEqual(occlusionPlan(OLEG, S, C, ALL))
    // сеток нет (воркер перезапущен) — ответ «нет сеток», клиент шлёт их снова
    fake.onmessage!({ data: { t: 'plan', id: 8, fp: 'другая', rec: OLEG, closeY: C, shown: [...ALL] } })
    expect(out[1]).toMatchObject({ t: 'plan', id: 8, plan: null, missing: true })
    // десна: сетка один раз, конечная форма — та же, что на месте
    const g = gumIn()
    fake.onmessage!({ data: { t: 'gum', gid: 3, gum: g } })
    const T = occlusionPlan(OLEG, S, C, ALL)!.teeth
    fake.onmessage!({ data: { t: 'shape', id: 9, fp, gid: 3, teeth: T } })
    const want = gumTarget(gumStore(g), S, T)
    expect(out[2]).toMatchObject({ t: 'shape', id: 9, missing: false })
    if (out[2]?.t === 'shape' && out[2].shape) {
      expect([...out[2].shape.pos]).toEqual([...want.pos])
      expect([...out[2].shape.nor]).toEqual([...want.nor])
    }
    fake.onmessage!({ data: { t: 'shape', id: 10, fp, gid: 99, teeth: T } })
    expect(out[3]).toMatchObject({ t: 'shape', id: 10, shape: null, missing: true })
  })

  it('⭐ форма десны: без плана — сетка раскладки и её нормали; план Олега двигает нижнюю десну; без воркера — тот же ответ', SLOW, async () => {
    const g = gumIn()
    const G = gumStore(g)
    const zero = gumTarget(G, S, ZERO_TEETH)
    expect([...zero.pos]).toEqual([...g.positions])
    expect([...zero.nor]).toEqual([...vertexNormals(g.positions, g.index)])
    const T = occlusionPlan(OLEG, S, C, ALL)!.teeth
    const moved = gumTarget(G, S, T)
    let d = 0
    for (let i = 0; i < moved.pos.length; i++) d = Math.max(d, Math.abs(moved.pos[i]! - g.positions[i]!))
    expect(d).toBeGreaterThan(1)   // сегменты ±4 мм и «веер»
    // без воркера — тот же ответ отложенно
    const gid = sendGum(g)
    const viaAsync = await requestGumShape(S, shapesPrint(S), gid, T)
    expect([...viaAsync!.pos]).toEqual([...moved.pos])
  })

  it('нормали вершин: площадной вес граней, единичные, как `computeVertexNormals` three', () => {
    // два треугольника в плоскости z = 0 (обход против часовой — нормаль +z) и один наклонный
    const pos = [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]
    const n = vertexNormals(pos, [0, 1, 2, 1, 3, 2])
    for (let v = 0; v < 4; v++) expect([n[v * 3], n[v * 3 + 1], n[v * 3 + 2]]).toEqual([0, 0, 1])
    const m = vertexNormals([0, 0, 0, 2, 0, 0, 0, 0, 2], [0, 1, 2])
    expect(m[1]).toBeCloseTo(-1, 6)
  })
})
