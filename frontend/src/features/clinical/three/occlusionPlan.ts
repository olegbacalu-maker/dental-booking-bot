import { toWorld, type PlacedTooth, type Vec3 } from './arch'
import {
  biteAt, classSign, jawPose, mmOf, molarMark, poseLower, SCHEMATIC_CLASS_SHIFT_MM, SCHEMATIC_TILT_II1_DEG,
  SCHEMATIC_TILT_II2_DEG, tiltSubtype, ZERO_POSE, type Bite, type BitePoints, type JawPose, type OcclGeo, type OcclRecord,
} from './occlusion'
import { torqued } from './pose'

/* Прикус в 3D, этап 4 (волна «ocluzie»; задание — `docs/dentpilot-2/ocluzie-3d.md`,
   решения Олега и координатора 07.11 — `D:\DentProject\review\ocluzie-3d-2026-11-07.md`):
   запись → план = поза нижней челюсти (`jawPose`) + места отдельных зубов. Чистые
   числа, без three: сцена отдаёт сетки коронок и места раскладки (`ToothShape`),
   модуль меряет и отвечает планом. Места зубов по плану — ОДНА формула `placeOf`
   и для сцены, и для замера (как `poseLower` у челюсти).

   Что двигается и почему:
   - II/1, II/2 — верхние резцы 11/21 (`tiltC`) и 12/22 (`tiltL`) наклоняются
     добавочным torque (`pose.torqued`) по подтипу, одинаковому с обеих сторон;
   - записанный overjet при записанном классе — резцы 11/21/12/22 сдвигаются по z
     (`incZ`) до записанного, но не дальше касания боковых резцов с клыками
     (`OVERJET_STOP_AT_CANINE`): недобранный остаток — `rest.oj`, на плашке — запись;
   - разные классы сторон — нижние 4–8 сдвигаются по сторонам (`segR`/`segL`),
     передний отрезок 43–33 поворачивается «веером» (`fan`) вокруг вертикали через
     середину 41|31: средняя линия на месте (её даёт только `dx`), клыки догоняют
     сегменты так, что промежутки 3|4 с обеих сторон ≥ 0 и равны;
   - III без записанного overbite — нижняя челюсть по вертикали до первого
     контакта любой пары верхняя–нижняя (`jawClear`: вверх до касания или вниз до
     снятия пересечения); открытый прикус — наклоном, сзади до касания;
     записанный overbite — после наклона резцов, но только до первого касания любой пары
     (`OVERBITE_STOP_AT_CONTACT`, Олег 08.11 «Без пересечения»); в конце любого плана
     челюсть вниз до касания, если коронки верх–низ где-то входят друг в друга. */

/** Коронка зуба для плана: место раскладки (`posed`, ДО прикуса), сетка коронки
 *  в системе зуба (позиции и индексы треугольников), ширина md. */
export interface ToothShape {
  place: PlacedTooth
  pos: ArrayLike<number>
  index: ArrayLike<number>
  md: number
  upper: boolean
}
export type Shapes = ReadonlyMap<number, ToothShape>

/** Места зубов по плану. Углы — в градусах (`tilt*`) и радианах (`fan`). */
export interface TeethPlan {
  /** добавочный torque верхних центральных (11, 21) и боковых (12, 22) резцов, градусы */
  tiltC: number
  tiltL: number
  /** сдвиг верхних резцов 11/21/12/22 по z (вперёд +), мм — добор записанного overjet */
  incZ: number
  /** сдвиг нижних 4–8 правой (4x) и левой (3x) стороны по z (вперёд +), мм */
  segR: number
  segL: number
  /** поворот нижних 43–33 вокруг вертикали через (0, fanPivot), рад; + — правая сторона вперёд */
  fan: number
  fanPivot: number
}

export const ZERO_TEETH: Readonly<TeethPlan> = Object.freeze({ tiltC: 0, tiltL: 0, incZ: 0, segR: 0, segL: 0, fan: 0, fanPivot: 0 })

export interface OcclPlan {
  jaw: JawPose
  teeth: TeethPlan
  /** что план не добрал (видно в зонде и стенде): overjet и overbite, мм (запись − модель);
   *  промежутки 3|4 справа и слева после «веера», мм (≥ 0 — без наложения) */
  rest: { oj: number; ob: number; gap34R: number | null; gap34L: number | null }
  base: Bite
  /** по каким зубам мерился прикус (показанные коронки, `picksOf`) */
  picks: Picks
}

/** Зубы замера прикуса: резцы overjet/overbite (`u`, `l`) и пары моляров класса по
 *  сторонам (верхний, нижний). null у стороны — ни одной пары с обеими коронками:
 *  класс этой стороны план не двигает. */
export interface Picks { u: number; l: number; R: readonly [number, number] | null; L: readonly [number, number] | null }
export const PICKS_ALL: Readonly<Picks> = Object.freeze({ u: 11, l: 41, R: [16, 46] as const, L: [26, 36] as const })

/** Замер только по ПОКАЗАННЫМ коронкам (координатор 08.11): удалённый, отсутствующий,
 *  имплантат без коронки — не ориентир. Класс — 16/46 (26/36), нет пары — соседняя
 *  17/47 (27/37), нет и её — сторона без замера. Резцы — 11/41, затем 21/31, 11/31,
 *  21/41, 12/42, 22/32; нет ни одной пары — 11/41 по раскладке (их место на дуге есть
 *  и без коронок), в плане это видно полем `picks`. */
export function picksOf(has: (n: number) => boolean): Picks {
  const pair = (opts: readonly (readonly [number, number])[]): readonly [number, number] | null =>
    opts.find(([a, b]) => has(a) && has(b)) ?? null
  const inc = pair([[11, 41], [21, 31], [11, 31], [21, 41], [12, 42], [22, 32]]) ?? [11, 41]
  return { u: inc[0], l: inc[1], R: pair([[16, 46], [17, 47]]), L: pair([[26, 36], [27, 37]]) }
}

/** Добор overjet сдвигом резцов назад — до касания боковых резцов с клыками,
 *  клыки на месте (координатор 07.11, отступление от «сохранять overjet» для
 *  крайних записей — в томе для Олега). false — добирать полностью. */
export const OVERJET_STOP_AT_CANINE = true
/** Записанный overbite добирается только до первого касания любой пары верх–низ
 *  (`jawClear`): коронки не пересекаются ни при каком сочетании записи (Олег 08.11:
 *  «Без пересечения»). Недобор — `rest.ob`, на плашке — запись врача (как у overjet).
 *  false — число врача любой ценой (решение 07.11, коронки входили до 2,2 мм). */
export const OVERBITE_STOP_AT_CONTACT = true
/** Записанный overbite после наклона резцов доводится снова: число врача
 *  главнее (координатор 07.11). false — dy от прикуса модели без наклона. */
export const OVERBITE_AFTER_TILT = true
/** Контакт моляров — только если какая-то сторона III и overbite не записан
 *  (координатор 07.11). I класс по умолчанию не трогается (`arch.test`, Q1). */
export const CONTACT_ONLY_III = true
/** Граница сегментов нижней дуги: зубы с этой позицией и дальше (4–8) идут со
 *  своей стороной, ближе (1–3) — «веером» (координатор 07.11, вариант (б2)). */
export const SEGMENT_FROM = 4

const isTeethZero = (t: TeethPlan): boolean => !t.tiltC && !t.tiltL && !t.incZ && !t.segR && !t.segL && !t.fan
export const teethMove = (t: TeethPlan | null | undefined): boolean => !!t && !isTeethZero(t)

const shift = (p: PlacedTooth, dx: number, dz: number): PlacedTooth =>
  ({ ...p, position: [p.position[0] + dx, p.position[1], p.position[2] + dz] })

/** Поворот вокруг вертикали через (px, pz) на a, + — правая сторона (−x) вперёд:
 *  x' = x·cos + z·sin, z' = −x·sin + z·cos — как `poseLower`. */
function yawAbout(p: PlacedTooth, a: number, px: number, pz: number): PlacedTooth {
  const c = Math.cos(a)
  const s = Math.sin(a)
  const r = (v: Vec3): Vec3 => [v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c]
  const q = r([p.position[0] - px, p.position[1], p.position[2] - pz])
  return { ...p, position: [q[0] + px, q[1], q[2] + pz], xAxis: r(p.xAxis), yAxis: r(p.yAxis), zAxis: r(p.zAxis) }
}

/** Место зуба n по плану при доле смыкания k (Q3: прикус только при «Ocluzie»).
 *  k = 0 или нулевой план — ТОТ ЖЕ объект `p0` (разомкнутое положение побайтно прежнее). */
export function placeOf(n: number, p0: PlacedTooth, t: TeethPlan, k: number): PlacedTooth {
  if (k <= 0 || isTeethZero(t)) return p0
  const q = Math.floor(n / 10)
  const i = n % 10
  let p = p0
  if (q === 1 || q === 2) {
    if (i === 1 || i === 2) {
      p = torqued(p, (i === 1 ? t.tiltC : t.tiltL) * k)
      if (t.incZ) p = shift(p, 0, t.incZ * k)
    }
  } else if (q === 3 || q === 4) {
    if (i >= SEGMENT_FROM) {
      const dz = (q === 4 ? t.segR : t.segL) * k
      if (dz) p = shift(p, 0, dz)
    } else if (t.fan) {
      p = yawAbout(p, t.fan * k, 0, t.fanPivot)
    }
  }
  return p
}

/** Точки коронки в системе челюсти при месте p (плоский массив xyz). */
export function crownPts(sh: ToothShape, p: PlacedTooth): number[] {
  const a = sh.pos
  const out: number[] = []
  for (let i = 0; i + 2 < a.length; i += 3) out.push(...toWorld(p, [a[i] as number, a[i + 1] as number, a[i + 2] as number]))
  return out
}

/** Тело для `sweep`: вершины (плоский xyz) и треугольники (индексы). */
export interface Body { p: ArrayLike<number>; idx: ArrayLike<number> }

/** На сколько мм тело A может пройти вдоль единичного d до касания тела B: по
 *  линиям вдоль d через вершины A (до треугольников B) и через вершины B (до
 *  треугольников A). Минус — тела уже входят друг в друга (на столько их надо
 *  развести); Infinity — по ходу A не встретит B. Точный по сетке, а не «по
 *  кругу вокруг вершины»: на скатах бугров круг 0,4 мм врал на десятые доли
 *  (фаза А этапа 4). */
export function sweep(A: Body, B: Body, d: Vec3, stride = 1): number {
  const n = Math.hypot(d[0], d[1], d[2]) || 1
  const e1: Vec3 = [d[0] / n, d[1] / n, d[2] / n]
  const h: Vec3 = Math.abs(e1[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]
  const cr = (u: Vec3, v: Vec3): Vec3 => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
  const e2 = cr(e1, h)
  const l2 = Math.hypot(...e2)
  const e2n: Vec3 = [e2[0] / l2, e2[1] / l2, e2[2] / l2]
  const e3 = cr(e1, e2n)
  const proj = (b: Body): Float64Array => {
    const o = new Float64Array(b.p.length)
    for (let i = 0; i + 2 < b.p.length; i += 3) {
      const x = b.p[i] as number
      const y = b.p[i + 1] as number
      const z = b.p[i + 2] as number
      o[i] = x * e1[0] + y * e1[1] + z * e1[2]
      o[i + 1] = x * e2n[0] + y * e2n[1] + z * e2n[2]
      o[i + 2] = x * e3[0] + y * e3[1] + z * e3[2]
    }
    return o
  }
  const PA = proj(A)
  const PB = proj(B)
  const CELL = 0.6
  const key = (ga: number, gb: number): number => (ga + 4096) * 8192 + (gb + 4096)
  /** треугольники тела по клеткам плоскости (a, b) — проверка вершины только в своей клетке */
  const grid = (P: Float64Array, idx: ArrayLike<number>): Map<number, number[]> => {
    const g = new Map<number, number[]>()
    for (let t = 0; t + 2 < idx.length; t += 3) {
      const ia = (idx[t] as number) * 3
      const ib = (idx[t + 1] as number) * 3
      const ic = (idx[t + 2] as number) * 3
      const a0 = Math.min(P[ia + 1] as number, P[ib + 1] as number, P[ic + 1] as number)
      const a1 = Math.max(P[ia + 1] as number, P[ib + 1] as number, P[ic + 1] as number)
      const b0 = Math.min(P[ia + 2] as number, P[ib + 2] as number, P[ic + 2] as number)
      const b1 = Math.max(P[ia + 2] as number, P[ib + 2] as number, P[ic + 2] as number)
      for (let ga = Math.floor(a0 / CELL); ga <= Math.floor(a1 / CELL); ga++) {
        for (let gb = Math.floor(b0 / CELL); gb <= Math.floor(b1 / CELL); gb++) {
          const k = key(ga, gb)
          const arr = g.get(k)
          if (arr) arr.push(t)
          else g.set(k, [t])
        }
      }
    }
    return g
  }
  /** наименьшая и наибольшая координата вдоль d, где линия через (a, b) пересекает тело; null — мимо */
  let hMin = 0
  let hMax = 0
  const hits = (P: Float64Array, idx: ArrayLike<number>, g: Map<number, number[]>, a: number, b: number): boolean => {
    const list = g.get(key(Math.floor(a / CELL), Math.floor(b / CELL)))
    if (!list) return false
    let any = false
    for (const t of list) {
      const ia = (idx[t] as number) * 3
      const ib = (idx[t + 1] as number) * 3
      const ic = (idx[t + 2] as number) * 3
      const ax = P[ia + 1] as number
      const az = P[ia + 2] as number
      const bx = P[ib + 1] as number
      const bz = P[ib + 2] as number
      const cx = P[ic + 1] as number
      const cz = P[ic + 2] as number
      const det = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
      if (Math.abs(det) < 1e-12) continue
      const w1 = ((bz - cz) * (a - cx) + (cx - bx) * (b - cz)) / det
      if (w1 < -1e-9) continue
      const w2 = ((cz - az) * (a - cx) + (ax - cx) * (b - cz)) / det
      if (w2 < -1e-9 || 1 - w1 - w2 < -1e-9) continue
      const v = w1 * (P[ia] as number) + w2 * (P[ib] as number) + (1 - w1 - w2) * (P[ic] as number)
      if (!any) {
        hMin = v
        hMax = v
        any = true
      } else {
        if (v < hMin) hMin = v
        if (v > hMax) hMax = v
      }
    }
    return any
  }
  let best = Infinity
  // вершины A идут вперёд к поверхности B
  const gB = grid(PB, B.idx)
  const st = 3 * Math.max(1, Math.floor(stride))
  for (let i = 0; i + 2 < PA.length; i += st) {
    if (!hits(PB, B.idx, gB, PA[i + 1] as number, PA[i + 2] as number)) continue
    const s = PA[i] as number
    if (hMax - s < 0) continue      // B позади — A от него уходит
    if (hMin - s < best) best = hMin - s   // < 0 — вершина A внутри B
  }
  // вершины B навстречу поверхности A
  const gA = grid(PA, A.idx)
  for (let i = 0; i + 2 < PB.length; i += st) {
    if (!hits(PA, A.idx, gA, PB[i + 1] as number, PB[i + 2] as number)) continue
    const s = PB[i] as number
    if (s - hMin < 0) continue      // A впереди вершины B — не встретятся
    if (s - hMax < best) best = s - hMax
  }
  return best
}

/** Оси, вдоль которых `depthOf` ищет разведение тел. */
const AXES: readonly Vec3[] = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]

/** Глубина пересечения тел, мм: наименьший сдвиг вдоль одной из осей ±x, ±y, ±z,
 *  который их разводит; 0 — не пересекаются. Вершина одного тела внутри другого
 *  даёт минус `sweep` по ЛЮБОЙ оси, поэтому хоть одна ось без минуса = пересечения нет. */
export function depthOf(A: Body, B: Body, stride = 1): number {
  let best = Infinity
  for (const d of AXES) {
    const s = sweep(A, B, d, stride)
    if (s >= 0) return 0
    if (-s < best) best = -s
  }
  return best
}

const marksCache = new WeakMap<ToothShape, Vec3 | null>()
const markOf = (sh: ToothShape): Vec3 | null => {
  if (!marksCache.has(sh)) marksCache.set(sh, molarMark(sh.pos, sh.md, sh.upper))
  return marksCache.get(sh) ?? null
}

/** Прикус модели при плане: точки замера по местам `placeOf` (k = 1) на зубах `pk`
 *  (сторона без пары — точки 16/46 или 26/36 раскладки: класс её не двигает). */
export function planBite(S: Shapes, t: TeethPlan, jaw: JawPose, upperY: number, lowerY: number, pk: Picks = PICKS_ALL): { bite: Bite; geo: OcclGeo } | null {
  const at = (n: number): { sh: ToothShape; p: PlacedTooth } | null => {
    const sh = S.get(n)
    return sh ? { sh, p: placeOf(n, sh.place, t, 1) } : null
  }
  const u11 = at(pk.u)
  const l41 = at(pk.l)
  const [r16, r46] = pk.R ?? [16, 46]
  const [r26, r36] = pk.L ?? [26, 36]
  const m = [r16, r26, r36, r46].map(at)
  if (!u11 || !l41 || m.some((x) => !x)) return null
  const [m16, m26, m36, m46] = m as { sh: ToothShape; p: PlacedTooth }[]
  const mk = (x: { sh: ToothShape; p: PlacedTooth }): Vec3 | null => {
    const k = markOf(x.sh)
    return k ? toWorld(x.p, k) : null
  }
  const pts: BitePoints = {
    u11: crownPts(u11.sh, u11.p), l41: crownPts(l41.sh, l41.p),
    c16: m16!.p.position, c26: m26!.p.position, c36: m36!.p.position, c46: m46!.p.position,
    k16: mk(m16!), k26: mk(m26!), k36: mk(m36!), k46: mk(m46!),
  }
  return biteAt(pts, jaw, upperY, lowerY)
}

/** Тело коронки n по плану; `lower` — с позой нижней челюсти и подъёмом группы. */
function bodyOf(S: Shapes, n: number, t: TeethPlan, map?: (q: Vec3) => Vec3): Body | null {
  const sh = S.get(n)
  if (!sh) return null
  const p = placeOf(n, sh.place, t, 1)
  const raw = crownPts(sh, p)
  if (map) {
    for (let i = 0; i + 2 < raw.length; i += 3) {
      const q = map([raw[i] as number, raw[i + 1] as number, raw[i + 2] as number])
      raw[i] = q[0]
      raw[i + 1] = q[1]
      raw[i + 2] = q[2]
    }
  }
  return { p: raw, idx: sh.index }
}

const BIG = 99
const fin = (v: number): number => (Number.isFinite(v) ? v : BIG)

/** Вертикальный зазор пар 16/46 и 26/36 при плане: на сколько нижнюю можно поднять до касания. */
export function molarGaps(S: Shapes, t: TeethPlan, jaw: JawPose, upperY: number, lowerY: number): { R: number; L: number } {
  const up = (q: Vec3): Vec3 => [q[0], q[1] + upperY, q[2]]
  const lo = (q: Vec3): Vec3 => poseLower(q, jaw, lowerY)
  const g = (u: number, l: number): number => {
    const U = bodyOf(S, u, t, up)
    const L = bodyOf(S, l, t, lo)
    return U && L ? sweep(L, U, [0, 1, 0]) : Infinity
  }
  return { R: g(16, 46), L: g(26, 36) }
}

/** Все показанные коронки по плану в системе мира: верхние со смыканием, нижние с позой
 *  челюсти; прямоугольник в плоскости xz — отбор пар для `jawClear`. */
interface Placed extends Body { n: number; x0: number; x1: number; z0: number; z1: number }
function placedAll(S: Shapes, t: TeethPlan, jaw: JawPose, upperY: number, lowerY: number): { up: Placed[]; lo: Placed[] } {
  const up: Placed[] = []
  const lo: Placed[] = []
  for (const [n, sh] of S) {
    const b = bodyOf(S, n, t, sh.upper ? (q) => [q[0], q[1] + upperY, q[2]] : (q) => poseLower(q, jaw, lowerY))
    if (!b) continue
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity
    for (let i = 0; i + 2 < b.p.length; i += 3) {
      const x = b.p[i] as number
      const z = b.p[i + 2] as number
      if (x < x0) x0 = x
      if (x > x1) x1 = x
      if (z < z0) z0 = z
      if (z > z1) z1 = z
    }
    ;(sh.upper ? up : lo).push({ ...b, n, x0, x1, z0, z1 })
  }
  return { up, lo }
}

/** Вертикальный зазор челюстей при плане: на сколько нижнюю можно поднять до первого
 *  касания ЛЮБОЙ пары верхняя–нижняя коронка; минус — коронки уже входят друг в друга
 *  (на столько опустить). Только 16/46 и 26/36 (`molarGaps`) мало: наклон открытого
 *  прикуса вокруг 46 поднимал 17/18/47/48 в верхние на 2–5 мм (данные Олега 08.11). */
export function jawClear(S: Shapes, t: TeethPlan, jaw: JawPose, upperY: number, lowerY: number): number {
  const { up, lo } = placedAll(S, t, jaw, upperY, lowerY)
  let best = Infinity
  for (const L of lo) {
    for (const U of up) {
      if (L.x0 > U.x1 || U.x0 > L.x1 || L.z0 > U.z1 || U.z0 > L.z1) continue
      const g = sweep(L, U, [0, 1, 0])
      if (g < best) best = g
    }
  }
  return best
}

/** Пересечения коронок верхняя–нижняя при плане (сомкнуто): пары с глубиной больше
 *  min, мм (`depthOf`) — та же проверка, что зонд сцены `overlaps()` по three. */
export function jawOverlaps(S: Shapes, t: TeethPlan, jaw: JawPose, upperY: number, lowerY: number, min = 0.01): { u: number; l: number; d: number }[] {
  const { up, lo } = placedAll(S, t, jaw, upperY, lowerY)
  const out: { u: number; l: number; d: number }[] = []
  for (const L of lo) {
    for (const U of up) {
      if (L.x0 > U.x1 || U.x0 > L.x1 || L.z0 > U.z1 || U.z0 > L.z1) continue
      const d = depthOf(U, L)
      if (d > min) out.push({ u: U.n, l: L.n, d })
    }
  }
  return out.sort((a, b) => b.d - a.d)
}

/** Промежуток 3|4 по стороне: на сколько 44 (34) может пройти мезиально до клыка. */
export function gap34(S: Shapes, t: TeethPlan, stride = 1): { R: number; L: number } {
  const g = (pm: number, c: number): number => {
    const sh = S.get(pm)
    const A = bodyOf(S, pm, t)
    const B = bodyOf(S, c, t)
    if (!sh || !A || !B) return Infinity
    const p = placeOf(pm, sh.place, t, 1)
    // мезиально — −x зуба; в плоскости дуги (y не трогаем)
    const d: Vec3 = [-p.xAxis[0], 0, -p.xAxis[2]]
    return sweep(A, B, d, stride)
  }
  return { R: g(44, 43), L: g(34, 33) }
}

/** Промежуток боковой резец → клык при движении резцов назад (−z), мм. */
export function gapIncCanine(S: Shapes, t: TeethPlan): number {
  const g = (inc: number, c: number): number => {
    const A = bodyOf(S, inc, t)
    const B = bodyOf(S, c, t)
    return A && B ? sweep(A, B, [0, 0, -1]) : Infinity
  }
  return Math.min(g(12, 13), g(22, 23))
}

/** Угол «веера»: промежутки 3|4 справа и слева ≥ 0 (без наложения) и наибольший
 *  из них наименьший. Зависимость от угла НЕ монотонна (клык поворачивается и
 *  уходит к языку, линия контакта меняется: справа при II/1 + III слева минимум
 *  ≈ 2 мм около −14,8°), поэтому не «равенство сторон» делением пополам, а
 *  минимум цены золотым сечением около оценки. Наложение неустранимо — наименьшее. */
function solveFan(S: Shapes, t: TeethPlan): { fan: number; R: number; L: number } {
  // сторона без клыка или первого премоляра (коронка не показана) — промежутка нет,
  // угол держит другая сторона; нет обеих — оценка
  const cost = (a: number, stride: number): { c: number; R: number; L: number } => {
    const g = gap34(S, { ...t, fan: a }, stride)
    const fs = [g.R, g.L].filter(Number.isFinite)
    if (!fs.length) return { c: 0, R: g.R, L: g.L }
    const lo = Math.min(...fs)
    return { c: lo < 0 ? 1000 - lo : Math.max(...fs), R: g.R, L: g.L }
  }
  const D = Math.PI / 180
  // оценка: клык (≈ 16 мм от середины) догоняет полуразницу сегментов; поиск — ±8° вокруг
  const est = Math.asin(Math.max(-1, Math.min(1, (t.segR - t.segL) / 2 / 16)))
  const e0 = cost(est, 1)
  if (!Number.isFinite(e0.R) && !Number.isFinite(e0.L)) return { fan: est, R: e0.R, L: e0.L }
  // золотое сечение по каждой второй вершине (грубо и быстро), итог — точным замером
  let lo = est - 8 * D
  let hi = est + 8 * D
  const G = (Math.sqrt(5) - 1) / 2
  let x1 = hi - G * (hi - lo)
  let x2 = lo + G * (hi - lo)
  let f1 = cost(x1, 2).c
  let f2 = cost(x2, 2).c
  for (let i = 0; i < 16; i++) {
    if (f1 < f2) {
      hi = x2
      x2 = x1
      f2 = f1
      x1 = hi - G * (hi - lo)
      f1 = cost(x1, 2).c
    } else {
      lo = x1
      x1 = x2
      f1 = f2
      x2 = lo + G * (hi - lo)
      f2 = cost(x2, 2).c
    }
  }
  const a = f1 < f2 ? x1 : x2
  const e = cost(a, 1)
  return { fan: a, R: e.R, L: e.L }
}

/** Шагов секущей для наклона открытого прикуса. */
const OPEN_STEPS = 4

/** Запись → план (`closeY` — смыкание каждой челюсти в сомкнутом положении, мм).
 *  `shown` — зубы с ПОКАЗАННОЙ коронкой (координатор 08.11): только они дают контакт,
 *  промежутки и ориентиры; не задан — все. Раскладка (`S`) нужна целиком: места дуги
 *  и опора «веера» есть и без коронок. */
export function occlusionPlan(rec0: OcclRecord, S: Shapes, closeY: number, shown?: ReadonlySet<number>): OcclPlan | null {
  const upperY = -closeY
  const lowerY = closeY
  const P: Shapes = shown ? new Map([...S].filter(([n]) => shown.has(n))) : S
  const picks = picksOf((n) => P.has(n))
  const tr = (v: string | undefined): string => (v ?? '').trim()
  // сторона без пары ориентиров — класс её не двигает (как не записанный)
  const rec: OcclRecord = { ...rec0, angle_dr: picks.R ? (rec0.angle_dr ?? '') : '', angle_st: picks.L ? (rec0.angle_st ?? '') : '' }
  const bite0 = (t: TeethPlan, j: JawPose) => planBite(S, t, j, upperY, lowerY, picks)
  const b0 = bite0(ZERO_TEETH, ZERO_POSE)
  if (!b0) return null
  const { bite: base, geo } = b0
  const jaw = jawPose(rec, base, geo)
  const teeth: TeethPlan = { ...ZERO_TEETH }
  const rest: OcclPlan['rest'] = { oj: 0, ob: 0, gap34R: null, gap34L: null }
  // подъём по МИРОВОЙ вертикали на d: t = (dx, dy, dz) идёт до поворота (`poseLower`),
  // поэтому Δt = Rx(pitch)ᵀ·(0, d, 0) — иначе при наклоне челюсть уезжала бы и вперёд
  const lift = (j: JawPose, d: number): void => {
    j.dy += d * Math.cos(j.pitch)
    j.dz -= d * Math.sin(j.pitch)
  }
  const kR = classSign(tr(rec.angle_dr))
  const kL = classSign(tr(rec.angle_st))
  const overjet = mmOf(rec.overjet)
  const overbite = mmOf(rec.overbite)
  const open = tr(rec.deschisa) !== ''

  // разные классы сторон: сегменты 4–8 по сторонам, передний отрезок «веером»
  if (kR !== null && kL !== null && kR !== kL) {
    const dzR = base.relR + kR * SCHEMATIC_CLASS_SHIFT_MM
    const dzL = base.relL + kL * SCHEMATIC_CLASS_SHIFT_MM
    const mean = (dzR + dzL) / 2
    teeth.segR = dzR - mean
    teeth.segL = dzL - mean
    const p41 = S.get(41)?.place.position
    const p31 = S.get(31)?.place.position
    teeth.fanPivot = p41 && p31 ? (p41[2] + p31[2]) / 2 : 0
    const f = solveFan(P, teeth)
    teeth.fan = f.fan
    rest.gap34R = f.R
    rest.gap34L = f.L
  }

  // наклон верхних резцов по подтипу (одинаковому справа и слева)
  const sub = tiltSubtype(rec)
  const tilt = sub === 'II/1' ? SCHEMATIC_TILT_II1_DEG : sub === 'II/2' ? SCHEMATIC_TILT_II2_DEG : null
  if (tilt) {
    teeth.tiltC = tilt.c
    teeth.tiltL = tilt.l
  }

  const obAt = (j: JawPose): number => bite0(teeth, j)?.bite.ob ?? base.ob

  // вертикаль: открытый прикус — наклоном; записанный overbite — его число после
  // наклона резцов; III без записи — до первого контакта любой пары верх–низ
  if (open) {
    // наклон вокруг 46 поднимает зубы позади опоры в верхние (2.11.0: 27/38 — 4,3 мм,
    // данные Олега 08.11). Поэтому при каждом наклоне челюсть стоит по вертикали до
    // первого касания любой пары (`jawClear`, без пересечения коронок), а наклон
    // подбирается секущей под overbite: сзади контакт, спереди открыто
    const want = overbite ?? -3
    // наклон вокруг опоры двигает ориентиры класса вдоль z (ниже опоры — вперёд):
    // dz возвращает класс, какой поза дала без наклона (при большом наклоне — до 0,5 мм)
    const relMean = (j: JawPose): number => {
      const b = bite0(teeth, j)?.bite
      return b ? (b.relR + b.relL) / 2 : 0
    }
    const rel0 = relMean({ ...jaw, pitch: 0, dy: 0 })
    const at = (pitch: number): JawPose => {
      const j = { ...jaw, pitch, dy: 0 }
      j.dz += relMean(j) - rel0
      const c = fin(jawClear(P, teeth, j, upperY, lowerY))
      if (c < BIG) lift(j, c)
      return j
    }
    let a = 0
    const ja = at(a)
    let fa = obAt(ja) - want
    let b = jaw.pitch
    let jb = b === a ? ja : at(b)
    let fb = obAt(jb) - want
    for (let i = 0; i < OPEN_STEPS * 2; i++) {
      if (Math.abs(fb) < 0.005 || Math.abs(fb - fa) < 1e-9) break
      const n = b - (fb * (b - a)) / (fb - fa)
      a = b
      fa = fb
      b = n
      jb = at(b)
      fb = obAt(jb) - want
    }
    jaw.pitch = jb.pitch
    jaw.dy = jb.dy
    jaw.dz = jb.dz
    // касание доводится ещё раз (сотые доли мм от перебора; overbite сдвигается на столько же)
    for (let i = 0; i < 3; i++) {
      const c = fin(jawClear(P, teeth, jaw, upperY, lowerY))
      if (c >= BIG || Math.abs(c) < 0.002) break
      lift(jaw, c)
    }
  } else if (overbite !== null) {
    if (OVERBITE_AFTER_TILT) {
      jaw.dy = 0
      jaw.dy = overbite - obAt(jaw)
    }
  } else if (!CONTACT_ONLY_III || kR === 1 || kL === 1) {
    // до первого контакта любой пары (не только 16/46 и 26/36: вторые и третьи
    // моляры сегментов разных сторон входили в верхние раньше)
    jaw.dy = 0
    const lift = fin(jawClear(P, teeth, jaw, upperY, lowerY))
    if (lift < BIG) jaw.dy = lift
  }

  // записанный overjet при записанном классе — сдвигом резцов, не дальше клыков
  if (overjet !== null && (kR !== null || kL !== null)) {
    const oj = bite0(teeth, jaw)?.bite.oj ?? base.oj
    let need = overjet - oj
    if (need < 0 && OVERJET_STOP_AT_CANINE) {
      const room = Math.max(0, fin(gapIncCanine(P, teeth)))
      need = Math.max(need, -room)
    }
    teeth.incZ = need
    const got = bite0(teeth, jaw)?.bite.oj ?? oj
    rest.oj = overjet - got
  }

  // без пересечения коронок верх–низ при ЛЮБОМ сочетании (Олег 08.11): записанный
  // overbite, срединная линия, наклон и сдвиг резцов, I/II без контакта III — челюсть
  // вниз до первого касания; недобор overbite — числом в плане
  if (OVERBITE_STOP_AT_CONTACT || overbite === null) {
    const c = fin(jawClear(P, teeth, jaw, upperY, lowerY))
    if (c < 0) lift(jaw, c)
  }
  if (overbite !== null) rest.ob = overbite - (bite0(teeth, jaw)?.bite.ob ?? overbite)
  return { jaw, teeth, rest, base, picks }
}
