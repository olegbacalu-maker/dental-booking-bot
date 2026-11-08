import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildJaw, LOWER, shapesOf, UPPER } from '../../../test/jaws'
import { GAP, GAP_CLOSED } from './arch'
import { gumWarpFrame } from './gum'
import { packed, peekPlan, planKey, requestFrame, requestPlan, resetOcclusionAsync, shapesPrint, type Reply } from './occlusionAsync'
import { occlusionPlan } from './occlusionPlan'

/* План прикуса вне главного потока (координатор 08.11): воркер считает ТЕМИ ЖЕ функциями,
   кэш — модуля (повторное открытие вкладки мгновенно), опоздавший ответ не путается.
   В jsdom воркера нет — запасной путь (тот же расчёт, отложенно); протокол самого воркера
   проверяется его обработчиком с подменённым `self`. */

const SLOW = { timeout: 30000 }
const C = (GAP - GAP_CLOSED) / 2
const S = shapesOf(buildJaw(UPPER, true), buildJaw(LOWER, false))
const ALL = new Set(S.keys())
const OLEG = { angle_dr: 'II/1', angle_st: 'III', incrucisata: '13-43', deschisa: '12-22' }

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

  it('⭐ воркер (обработчик с подменённым self): сетки один раз, план равен плану на месте, рамка десны — та же', SLOW, async () => {
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
    // рамка десны
    const pos = new Float32Array([0, 0, 20, 10, -2, 5, -10, -2, 5, 20, -1, -15])
    const teeth = [{ u: -0.5, neckY: 0, x: -10, z: 5 }, { u: 0.5, neckY: 0, x: 10, z: 5 }]
    fake.onmessage!({ data: { t: 'frame', id: 9, positions: pos, A: 25, D: 40, apex: 0.3, teeth, occ: -1 } })
    const fr = gumWarpFrame(pos, 25, 40, 0.3, teeth, -1)
    expect(out[2]).toMatchObject({ t: 'frame', id: 9 })
    if (out[2]?.t === 'frame') {
      expect([...out[2].u]).toEqual([...fr.u])
      expect([...out[2].depth]).toEqual([...fr.depth])
    }
  })

  it('рамка десны без воркера — та же, что на месте', async () => {
    const pos = new Float32Array([0, 0, 20, 10, -2, 5, -10, -2, 5])
    const teeth = [{ u: -0.5, neckY: 0, x: -10, z: 5 }, { u: 0.5, neckY: 0, x: 10, z: 5 }]
    const fr = await requestFrame(pos, 25, 40, 0.3, teeth, 1)
    const want = gumWarpFrame(pos, 25, 40, 0.3, teeth, 1)
    expect([...fr.u]).toEqual([...want.u])
    expect([...fr.depth]).toEqual([...want.depth])
  })
})
