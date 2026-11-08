import type { OcclRecord } from './occlusion'
import { gumStore, gumTarget, type GumIn, type GumShape, type GumStore } from './occlusionGum'
import { occlusionPlan, type OcclPlan, type Shapes, type TeethPlan, type ToothShape } from './occlusionPlan'
import OcclWorker from './occlusionWorker?worker&inline'

/* Прикус в 3D: план и десна — в воркере (координатор 08.11). План разных классов сторон
   стоил на главном потоке до 0,6 с одной задачей (подбор «веера», касание по всем парам),
   первая деформация десны — 50–100 мс кадром. Теперь сцена рисуется сразу (без плана или
   с прошлым), план приходит сообщением и едет тем же твином 700 мс; конечную форму десны
   считает воркер, кадры твина только смешивают. Кэш планов — модуля, не сцены: повторное
   открытие вкладки (новая сцена) берёт готовый. Без воркера (jsdom проверок, отказ
   браузера) — тот же расчёт на месте, но отложенно. */

/** Сетки коронок воркеру — один раз на раскладку (отпечаток `shapesPrint`). */
export interface ShapeMsg { t: 'shapes'; fp: string; shapes: [number, ToothShape][] }
/** Сетка десны воркеру — один раз на сетку (`gid`); рамку он считает сам. */
export interface GumMsg { t: 'gum'; gid: number; gum: GumIn }
export interface AskPlan { t: 'plan'; id: number; fp: string; rec: OcclRecord; closeY: number; shown: number[] }
export interface AskShape { t: 'shape'; id: number; fp: string; gid: number; teeth: TeethPlan }
export type Reply =
  | { t: 'plan'; id: number; plan: OcclPlan | null; missing: boolean }
  | { t: 'shape'; id: number; shape: GumShape | null; missing: boolean }

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
let gseq = 0
const waiting = new Map<number, { msg: AskPlan | AskShape; done: (r: Reply) => void }>()
const sent = new Set<string>()            // отпечатки, чьи сетки воркер уже получил
const sentGum = new Set<number>()         // сетки десны, которые воркер уже получил
const local = new Map<string, Shapes>()   // те же сетки на месте — для запасного пути и повтора
const gums = new Map<number, GumIn>()     // сетки десны на месте — для повтора и запасного пути
const stores = new Map<number, GumStore>() // рамки, посчитанные на месте (запасной путь)

/** Ответ без воркера — те же функции на главном потоке. */
function here(m: AskPlan | AskShape): Reply {
  if (m.t === 'plan') {
    const S = local.get(m.fp)
    return { t: 'plan', id: m.id, plan: S ? occlusionPlan(m.rec, S, m.closeY, new Set(m.shown)) : null, missing: false }
  }
  const S = local.get(m.fp)
  const g = gums.get(m.gid)
  if (!S || !g) return { t: 'shape', id: m.id, shape: null, missing: false }
  let G = stores.get(m.gid)
  if (!G) {
    G = gumStore(g)
    stores.set(m.gid, G)
  }
  return { t: 'shape', id: m.id, shape: gumTarget(G, S, m.teeth), missing: false }
}

function lose(): void {
  worker?.terminate()
  worker = null
  sent.clear()
  sentGum.clear()
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

function ask(m: AskPlan | AskShape): Promise<Reply> {
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

/** Сетки раскладки — воркеру один раз и на место (запасной путь, повтор). */
function ensureShapes(S: Shapes, fp: string): void {
  local.set(fp, S)
  if (local.size > 3) local.delete(local.keys().next().value as string)
  const w = workerOf()
  if (w && !sent.has(fp)) {
    const msg: ShapeMsg = { t: 'shapes', fp, shapes: packed(S) }
    w.postMessage(msg)
    sent.add(fp)
  }
}

const flying = new Map<string, Promise<OcclPlan | null>>()
/** План записи — из кэша модуля, иначе воркером (один расчёт на ключ, даже если
 *  просят дважды). Сетки воркеру уходят один раз на раскладку. */
export function requestPlan(S: Shapes, fp: string, closeY: number, rec: OcclRecord, shown: ReadonlySet<number>, key: string): Promise<OcclPlan | null> {
  const hit = peekPlan(key)
  if (hit !== undefined) return Promise.resolve(hit)
  const f = flying.get(key)
  if (f) return f
  const go = async (retry: boolean): Promise<OcclPlan | null> => {
    ensureShapes(S, fp)
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

/** Сетка десны — воркеру (рамку он считает сам); номер сетки для `requestGumShape`. */
export function sendGum(g: GumIn): number {
  const gid = ++gseq
  gums.set(gid, g)
  while (gums.size > 8) {
    const old = gums.keys().next().value as number
    gums.delete(old)
    stores.delete(old)
  }
  const w = workerOf()
  if (w) {
    const msg: GumMsg = { t: 'gum', gid, gum: g }
    w.postMessage(msg)
    sentGum.add(gid)
  }
  return gid
}

/** Конечная форма десны `gid` при плане зубов — воркером. null — сетка забыта. */
export async function requestGumShape(S: Shapes, fp: string, gid: number, teeth: TeethPlan): Promise<GumShape | null> {
  const go = async (retry: boolean): Promise<GumShape | null> => {
    ensureShapes(S, fp)
    const w = workerOf()
    const g = gums.get(gid)
    if (w && g && !sentGum.has(gid)) {
      const msg: GumMsg = { t: 'gum', gid, gum: g }
      w.postMessage(msg)
      sentGum.add(gid)
    }
    const r = await ask({ t: 'shape', id: ++seq, fp, gid, teeth })
    if (r.t !== 'shape') return null
    if (r.missing && retry) {
      sent.delete(fp)
      sentGum.delete(gid)
      return go(false)
    }
    return r.shape
  }
  return go(true)
}

/** Для проверок: забыть кэш и воркер. */
export function resetOcclusionAsync(): void {
  plans.clear()
  flying.clear()
  local.clear()
  gums.clear()
  stores.clear()
  lose()
  worker = undefined
}
