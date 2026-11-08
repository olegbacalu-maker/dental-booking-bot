import { gumWarpFrame } from './gum'
import type { OcclRecord } from './occlusion'
import { occlusionPlan, type OcclPlan, type Shapes, type ToothShape } from './occlusionPlan'
import OcclWorker from './occlusionWorker?worker&inline'

/* Прикус в 3D: план и рамка десны — в воркере (координатор 08.11). План разных классов
   сторон стоил на главном потоке ~0,6 с (подбор «веера» и касание по всем парам), рамка
   десны — 60–100 мс при первом «Ocluzie»: рывок при открытии вкладки. Теперь сцена рисуется
   сразу (без плана или с прошлым), план приходит сообщением и едет тем же твином 700 мс.
   Кэш планов — модуля, не сцены: повторное открытие вкладки (новая сцена) берёт готовый.
   Без воркера (jsdom проверок, отказ браузера) — тот же расчёт на месте, но отложенно. */

/** Сетки коронок воркеру — один раз на раскладку (отпечаток `shapesPrint`). */
export interface ShapeMsg { t: 'shapes'; fp: string; shapes: [number, ToothShape][] }
export interface AskPlan { t: 'plan'; id: number; fp: string; rec: OcclRecord; closeY: number; shown: number[] }
export interface FrameTooth { u: number; neckY: number; x: number; z: number }
export interface AskFrame { t: 'frame'; id: number; positions: Float32Array; A: number; D: number; apex: number; teeth: FrameTooth[]; occ: number }
export type Reply =
  | { t: 'plan'; id: number; plan: OcclPlan | null; missing: boolean }
  | { t: 'frame'; id: number; u: Float32Array; depth: Float32Array }
export interface Frame { u: Float32Array; depth: Float32Array }

/** Отпечаток раскладки: номера, места, оси и размер сеток коронок (FNV-1a по
 *  округлённым числам). Тот же пациент с теми же размерами зубов — тот же отпечаток. */
export function shapesPrint(S: Shapes): string {
  let h = 2166136261
  const mix = (v: number): void => {
    const s = Math.round(v * 1e4) | 0
    h = Math.imul(h ^ (s & 0xffff), 16777619)
    h = Math.imul(h ^ (s >>> 16), 16777619)
  }
  for (const [n, sh] of [...S].sort((a, b) => a[0] - b[0])) {
    mix(n)
    for (const v of [...sh.place.position, ...sh.place.xAxis, ...sh.place.yAxis, ...sh.place.zAxis]) mix(v)
    mix(sh.md)
    mix(sh.upper ? 1 : 0)
    mix(sh.pos.length)
    mix(sh.index.length)
    const L = sh.pos.length
    for (const i of [0, 1, 2, Math.floor(L / 2), L - 1]) if (i >= 0 && i < L) mix(sh.pos[i] as number)
  }
  return `${(h >>> 0).toString(36)}:${S.size}`
}

/** Ключ плана: раскладка, смыкание, запись и скрытые зубы (`look.crown`). */
export function planKey(fp: string, closeY: number, rec: OcclRecord, hidden: readonly number[]): string {
  return `${fp}|${closeY}|${JSON.stringify(rec)}|${hidden.join(',')}`
}

const PLAN_MAX = 24
const plans = new Map<string, OcclPlan | null>()
/** Готовый план из кэша модуля (undefined — не считался). */
export function peekPlan(key: string): OcclPlan | null | undefined {
  if (!plans.has(key)) return undefined
  const p = plans.get(key) ?? null
  plans.delete(key)
  plans.set(key, p)   // свежий — в конец (вытесняется самый старый)
  return p
}
function keep(key: string, p: OcclPlan | null): void {
  plans.set(key, p)
  while (plans.size > PLAN_MAX) plans.delete(plans.keys().next().value as string)
}

let worker: Worker | null | undefined   // undefined — не пробовали; null — нет
let seq = 0
const waiting = new Map<number, { msg: AskPlan | AskFrame; done: (r: Reply) => void }>()
const sent = new Set<string>()            // отпечатки, чьи сетки воркер уже получил
const local = new Map<string, Shapes>()   // те же сетки на месте — для запасного пути

/** Ответ без воркера — те же функции на главном потоке. */
function here(m: AskPlan | AskFrame): Reply {
  if (m.t === 'plan') {
    const S = local.get(m.fp)
    return { t: 'plan', id: m.id, plan: S ? occlusionPlan(m.rec, S, m.closeY, new Set(m.shown)) : null, missing: false }
  }
  const fr = gumWarpFrame(m.positions, m.A, m.D, m.apex, m.teeth, m.occ)
  return { t: 'frame', id: m.id, u: fr.u, depth: fr.depth }
}

function lose(): void {
  worker?.terminate()
  worker = null
  sent.clear()
  const all = [...waiting.values()]
  waiting.clear()
  for (const w of all) setTimeout(() => w.done(here(w.msg)), 0)
}

function workerOf(): Worker | null {
  if (worker !== undefined) return worker
  if (typeof Worker === 'undefined') return (worker = null)
  try {
    const w = new OcclWorker()
    w.onmessage = (ev: MessageEvent<Reply>) => {
      const r = ev.data
      const it = waiting.get(r.id)
      if (!it) return
      waiting.delete(r.id)
      it.done(r)
    }
    w.onerror = () => lose()
    worker = w
  } catch {
    worker = null
  }
  return worker
}

function ask(m: AskPlan | AskFrame): Promise<Reply> {
  return new Promise((done) => {
    const w = workerOf()
    if (!w) {
      // без воркера — отложенно, чтобы вызывающий успел дорисовать кадр
      setTimeout(() => done(here(m)), 0)
      return
    }
    waiting.set(m.id, { msg: m, done })
    w.postMessage(m)
  })
}

/** Сетки коронок — типизированными массивами (копия памяти, не полмиллиона чисел по одному). */
export function packed(S: Shapes): [number, ToothShape][] {
  return [...S].map(([n, sh]) => [n, { ...sh, pos: Float64Array.from(sh.pos), index: Uint32Array.from(sh.index) }])
}

const flying = new Map<string, Promise<OcclPlan | null>>()
/** План записи — из кэша модуля, иначе воркером (один расчёт на ключ, даже если
 *  просят дважды). Сетки воркеру уходят один раз на раскладку. */
export function requestPlan(S: Shapes, fp: string, closeY: number, rec: OcclRecord, shown: ReadonlySet<number>, key: string): Promise<OcclPlan | null> {
  const hit = peekPlan(key)
  if (hit !== undefined) return Promise.resolve(hit)
  const f = flying.get(key)
  if (f) return f
  local.set(fp, S)
  if (local.size > 3) local.delete(local.keys().next().value as string)
  const go = async (retry: boolean): Promise<OcclPlan | null> => {
    const w = workerOf()
    if (w && !sent.has(fp)) {
      const msg: ShapeMsg = { t: 'shapes', fp, shapes: packed(S) }
      w.postMessage(msg)
      sent.add(fp)
    }
    const r = await ask({ t: 'plan', id: ++seq, fp, rec, closeY, shown: [...shown] })
    if (r.t !== 'plan') return null
    if (r.missing && retry) {
      sent.delete(fp)
      return go(false)
    }
    return r.plan
  }
  const p = go(true).then((plan) => {
    keep(key, plan)
    flying.delete(key)
    return plan
  })
  flying.set(key, p)
  return p
}

/** Рамка деформации десны (`gum.gumWarpFrame`: станция дуги и глубина каждой вершины) — воркером. */
export async function requestFrame(positions: Float32Array, A: number, D: number, apex: number, teeth: FrameTooth[], occ: number): Promise<Frame> {
  // копия без передачи владения: если воркер упадёт, запасной путь посчитает по ней же
  const r = await ask({ t: 'frame', id: ++seq, positions: Float32Array.from(positions), A, D, apex, teeth, occ })
  return r.t === 'frame' ? { u: r.u, depth: r.depth } : gumWarpFrame(positions, A, D, apex, teeth, occ)
}

/** Для проверок: забыть кэш и воркер. */
export function resetOcclusionAsync(): void {
  plans.clear()
  flying.clear()
  local.clear()
  lose()
  worker = undefined
}
