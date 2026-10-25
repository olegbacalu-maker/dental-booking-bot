import type { ToothGeom } from '../chart'
import type { CrownInput, CrownModel } from './crown'
import { oneGroup, type RawMesh } from './mesh'
import { SURF, toCls, type Letter } from './toothGeometry'

/* Коронка по СВОЕЙ вылепленной модели (06.10, слово Олега «сделаем свои
   модели»; 07.10 — все 16 типов постоянных зубов). Модель лепит офлайн-
   генератор `scripts/teeth` (SDF: лофт сечений по трём силуэтам, бугры,
   валики, фиссуры) и запекает в таблицу: радиус стенки по высоте и углу вокруг
   центра сечения + высоты жевательной поверхности кольцами к центру. Таблицы
   едут файлом `/static/js/teeth.js` (`loadTeeth.ts`). Здесь — только постройка
   сетки по таблице и масштаб к размерам сервера (md, bl, crown): форма своя,
   размеры — клиники. Интерфейс тот же, что у `crownModel`, поэтому десна
   (`gum.ts` садится на `surf`), корни (`neck`) и слой пародонта работают без
   правок. */

export interface SculptTable {
  type: string
  /** размеры эталона, по которым лепили, мм */
  ref: { md: number; bl: number; crown: number }
  /** высота, до которой стенка задана радиусами; выше — жевательная поверхность */
  hCap: number
  /** число углов по кругу */
  theta: number
  heights: number[]
  /** центр сечения на каждой высоте */
  cx: number[]
  cz: number[]
  /** радиус стенки [высота][угол] от центра сечения, мм эталона */
  r: number[][]
  /** высоты жевательной поверхности [кольцо][угол], кольца от контура к центру */
  cap: number[][]
  /** доля радиуса верхнего ряда стенки у каждого кольца (07.10: гуще у края);
   *  нет — кольца поровну, как в образце 06.10 */
  capS?: number[]
  capCenter: number
  /** корни (25.10, `scripts/teeth/roots.py`); нет — корни-формула, как до 25.10 */
  roots?: RootSet
}

/** Ствол корня от шейки: глубины (мм эталона, вниз), сдвиг центра от центра
 *  шейки и множитель радиуса ШЕЙКИ на каждом угле — первая строка ровно 1, так
 *  что корень продолжает шейку без шва по построению. */
export interface RootTrunk {
  d: number[]
  ox: number[]
  oz: number[]
  w: number[][]
}

/** Корень многокорневого зуба: глубины, центр и радиусы сечения (мм эталона);
 *  начинается внутри ствола, последняя строка — апекс. */
export interface RootWall {
  d: number[]
  cx: number[]
  cz: number[]
  r: number[][]
}

export interface RootSet {
  /** глубина апекса самого длинного корня под шейкой, мм эталона: к длине сервера */
  len: number
  /** глубина фуркации (у однокорневого — `len`: ствол и есть корень) */
  fur: number
  /** углов у ствола и у корней */
  theta: number
  rt: number
  trunk: RootTrunk
  /** корни многокорневого; у однокорневого пусто */
  list: RootWall[]
}

/** Корней по таблице: у однокорневого список пуст — корень один, это ствол. */
export const rootCount = (rs: RootSet): number => rs.list.length || 1

/** Самое узкое сечение ствола, на которое ещё садится край десны: 0,7 шейки —
 *  та же граница, что у формулы (`w ≥ 0,7`). Глубже (рецессия 8–15 мм) край
 *  держится сечения на этой глубине: у апекса однокорневого корень вдвое уже,
 *  и тело десны (`gum.ts`) за таким краем не успевает — край повисал в 1 мм от
 *  десны (проверка «рецессия до предела» на своих моделях, 25.10). */
export const SURF_W_MIN = 0.7

/** Глубина ствола (мм эталона), до которой `surf` идёт по самому стволу: строки,
 *  пока средний множитель не меньше `SURF_W_MIN`, у многокорневого — не глубже фуркации. */
export function surfDepth(rs: RootSet): number {
  const D = rs.trunk.d
  let lim = 0
  for (let k = 0; k < D.length; k++) {
    const row = rs.trunk.w[k] ?? []
    const mean = row.reduce((a, b) => a + b, 0) / Math.max(1, row.length)
    if (mean < SURF_W_MIN) break
    lim = D[k] ?? lim
  }
  return rs.list.length ? Math.min(lim, rs.fur) : lim
}

/** Глубина апекса самого длинного корня = шеечный переход формулы (1,5 мм) +
 *  длина корня сервера: та же, что у формулы `buildRoots`, — под неё рассчитана
 *  глубина тела десны (`gum.ts`: 1,5 + 1,05·root + 1,8). */
export const ROOT_NECK = 1.5

type SculptInput = CrownInput & Partial<Pick<ToothGeom, 'root' | 'roots'>>

/** Набор своих моделей: таблицы по типу (`U1`…`L8`) и номер FDI → тип.
 *  Едет отдельным файлом `/static/js/teeth.js` (`loadTeeth.ts`), не в бандле. */
export interface SculptSet {
  SCULPT: Record<string, SculptTable>
  SCULPT_OF: Record<number, string>
}

const lin = (c: number): number => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
const CERV = [0.95, 0.86, 0.72].map(lin)
const EDGE = [0.9, 0.92, 0.95].map(lin)
const FOSSA = [0.8, 0.75, 0.66].map(lin)
const mix3 = (a: number[], b: number[], k: number): number[] => a.map((v, i) => v + ((b[i] ?? v) - v) * k)
const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v))
const smooth = (e0: number, e1: number, x: number): number => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1)
  return t * t * (3 - 2 * t)
}

/** Смыкание контактов (07.10, Олег: «слишком большое расстояние между зубами»):
 *  дуга оставляет между зубами 0,3 мм (`TOOTH_GAP`), и у формулы с её плоскими
 *  боковыми стенками это читается как касание, а у своей модели контакт —
 *  точка на выпуклой стенке, и щель видна. +3 % по ширине её закрывают. */
const CONTACT = 1.03

export function sculptModel(tab: SculptTable, g: SculptInput): CrownModel {
  const sx = (g.md / tab.ref.md) * CONTACT
  const sz = g.bl / tab.ref.bl
  const sy = g.crown / tab.ref.crown
  const N = tab.theta
  const K = tab.heights.length
  const cls = toCls(g.cls)
  const front = cls === 'incisor_c' || cls === 'incisor_l' || cls === 'canine'
  const H = tab.ref.crown
  const shade = (yRef: number): number[] => {
    const t = yRef / H
    let c = mix3(CERV, [1, 1, 1], smooth(0.0, 0.42, t))
    if (front) c = mix3(c, EDGE, smooth(0.72, 1, t) * 0.85)
    return c
  }

  /** точка стенки эталона: строка k, угол j (j по кругу) */
  const wallRef = (k: number, j: number): [number, number] => {
    const jj = ((j % N) + N) % N
    const a = (2 * Math.PI * jj) / N
    const r = tab.r[k]?.[jj] ?? 0
    return [(tab.cx[k] ?? 0) + r * Math.cos(a), (tab.cz[k] ?? 0) + r * Math.sin(a)]
  }

  const pos: number[] = []
  const col: number[] = []
  for (let k = 0; k < K; k++) {
    const y = tab.heights[k] ?? 0
    const c = shade(y)
    for (let j = 0; j < N; j++) {
      const [x, z] = wallRef(k, j)
      pos.push(x * sx, y * sy, z * sz)
      col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
    }
  }
  // жевательная поверхность: кольца от верхнего ряда стенки к центру
  const R = tab.cap.length + 1
  const kc = K - 1
  const cxc = tab.cx[kc] ?? 0
  const czc = tab.cz[kc] ?? 0
  // глубина ямок — по внутренней половине стола: край (стык со стенкой) ниже
  // любой ямки и растягивал бы шкалу так, что ямки почти не темнели
  let capMax = tab.capCenter
  let capMin = tab.capCenter
  tab.cap.forEach((ring, i) => {
    const s = tab.capS?.[i] ?? 1 - (i + 1) / (tab.cap.length + 1)
    for (const v of ring) {
      capMax = Math.max(capMax, v)
      if (s < 0.6) capMin = Math.min(capMin, v)
    }
  })
  const deepOf = (y: number): number => (capMax > capMin ? smooth(0.45, 0.95, (capMax - y) / (capMax - capMin)) : 0)
  const ringStart: number[] = [kc * N]
  for (let i = 1; i < R; i++) {
    const s = tab.capS?.[i - 1] ?? 1 - i / R
    // тон ямки — только внутри стола: у края кольца низко (стык со стенкой), и
    // «глубина» по высоте красила там поясок по всей коронке
    const inner = smooth(0.2, 0.5, 1 - s)
    ringStart.push(pos.length / 3)
    for (let j = 0; j < N; j++) {
      const a = (2 * Math.PI * j) / N
      const r = tab.r[kc]?.[j] ?? 0
      const y = tab.cap[i - 1]?.[j] ?? tab.hCap
      pos.push((cxc + s * r * Math.cos(a)) * sx, y * sy, (czc + s * r * Math.sin(a)) * sz)
      const c = mix3(shade(y), FOSSA, front ? 0 : deepOf(y) * 0.85 * inner)
      col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
    }
  }
  ringStart.push(pos.length / 3)
  pos.push(cxc * sx, tab.capCenter * sy, czc * sz)
  {
    const c = mix3(shade(tab.capCenter), FOSSA, front ? 0 : deepOf(tab.capCenter) * 0.85)
    col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
  }

  const B: Record<Letter, number[]> = { O: [], V: [], L: [], M: [], D: [] }
  const step = 360 / N
  const sector = (deg: number): Letter => {
    let d = deg % 360
    if (d < -30) d += 360
    if (d >= 330) d -= 360
    if (d >= -30 && d < 30) return 'D'
    if (d < 150) return 'V'
    if (d < 210) return 'M'
    return 'L'
  }
  for (let k = 0; k < K - 1; k++) {
    for (let j = 0; j < N; j++) {
      const jn = (j + 1) % N
      const a = k * N + j
      const b = k * N + jn
      const c = (k + 1) * N + jn
      const d = (k + 1) * N + j
      B[sector((j + 0.5) * step)].push(a, c, b, a, d, c)
    }
  }
  for (let i = 0; i < R - 1; i++) {
    const o = ringStart[i] ?? 0
    const inn = ringStart[i + 1] ?? 0
    if (i === R - 2) {
      for (let j = 0; j < N; j++) B.O.push(o + j, inn, o + ((j + 1) % N))
    } else {
      for (let j = 0; j < N; j++) {
        const jn = (j + 1) % N
        B.O.push(o + j, inn + j, inn + jn, o + j, inn + jn, o + jn)
      }
    }
  }
  const index: number[] = []
  const groups = SURF.map((L, slot) => {
    const start = index.length
    for (const v of B[L]) index.push(v)
    return { start, count: B[L].length, materialIndex: slot }
  })

  /** стенка по таблице: высота эталона между строками, угол между отсчётами */
  const wallAt = (th: number, hRef: number): [number, number] => {
    let k = 0
    while (k < K - 2 && hRef > (tab.heights[k + 1] ?? Infinity)) k++
    const h0 = tab.heights[k] ?? 0
    const h1 = tab.heights[k + 1] ?? h0
    const fk = h1 > h0 ? clamp((hRef - h0) / (h1 - h0), 0, 1) : 0
    let a = th % (2 * Math.PI)
    if (a < 0) a += 2 * Math.PI
    const fj = (a / (2 * Math.PI)) * N
    const j0 = Math.floor(fj)
    const tj = fj - j0
    const at = (kk: number): [number, number] => {
      const p0 = wallRef(kk, j0)
      const p1 = wallRef(kk, j0 + 1)
      return [p0[0] + (p1[0] - p0[0]) * tj, p0[1] + (p1[1] - p0[1]) * tj]
    }
    const q0 = at(k)
    const q1 = at(k + 1)
    return [(q0[0] + (q1[0] - q0[0]) * fk) * sx, (q0[1] + (q1[1] - q0[1]) * fk) * sz]
  }
  const neck = (th: number): [number, number] => wallAt(th, 0)
  // корни по таблице (25.10) — только если их столько же, сколько у сервера:
  // иначе (старая таблица, чужой номер) корни и стенка ниже шейки — формула
  const rs = tab.roots
  const root = g.root
  const roots = rs && root !== undefined && rootCount(rs) === (g.roots ?? 1) ? rs : null
  const sd = roots ? (ROOT_NECK + (root ?? 0)) / roots.len : 1
  const surfLim = roots ? surfDepth(roots) : 0
  const c0x = (tab.cx[0] ?? 0) * sx
  const c0z = (tab.cz[0] ?? 0) * sz
  /** точка ствола: строка k (до k+1 — доля fk), угол th */
  const trunkPt = (rr: RootSet, k: number, fk: number, th: number): [number, number] => {
    const tr = rr.trunk
    const T = rr.theta
    let a = th % (2 * Math.PI)
    if (a < 0) a += 2 * Math.PI
    const fj = (a / (2 * Math.PI)) * T
    const j0 = Math.floor(fj) % T
    const tj = fj - Math.floor(fj)
    const wAt = (kk: number): number => {
      const row = tr.w[kk] ?? []
      return (row[j0] ?? 1) + ((row[(j0 + 1) % T] ?? 1) - (row[j0] ?? 1)) * tj
    }
    const k1 = Math.min(k + 1, tr.d.length - 1)
    const w = wAt(k) + (wAt(k1) - wAt(k)) * fk
    const ox = (tr.ox[k] ?? 0) + ((tr.ox[k1] ?? 0) - (tr.ox[k] ?? 0)) * fk
    const oz = (tr.oz[k] ?? 0) + ((tr.oz[k1] ?? 0) - (tr.oz[k] ?? 0)) * fk
    const [nx, nz] = neck(th)
    return [c0x + (nx - c0x) * w + ox * sx, c0z + (nz - c0z) * w + oz * sz]
  }
  /** стенка ствола на глубине d мм эталона */
  const trunkAt = (rr: RootSet, th: number, d: number): [number, number] => {
    const D = rr.trunk.d
    let k = 0
    while (k < D.length - 2 && d > (D[k + 1] ?? Infinity)) k++
    const d0 = D[k] ?? 0
    const d1 = D[k + 1] ?? d0
    return trunkPt(rr, k, d1 > d0 ? clamp((d - d0) / (d1 - d0), 0, 1) : 0, th)
  }
  const surf = (th: number, h: number): [number, number] => {
    if (h >= 0) return wallAt(th, Math.min(h / sy, tab.hCap))
    if (roots) {
      // корень по таблице — ТА ЖЕ стенка, что у сетки корня: десна при рецессии
      // садится на неё; глубже `surfDepth` (корень уже 0,7 шейки, у многокорневого
      // — фуркация) — сечение на этой глубине
      return trunkAt(roots, th, Math.min(-h / sd, surfLim))
    }
    // корень — то же правило, что у `buildRoots`: сечение шейки сужается к корню
    const d = -h
    const w = d <= 2.4 ? 1 - 0.14 * smooth(0, 2.4, d) : Math.max(0.7, 0.86 - 0.03 * (d - 2.4))
    const [x, z] = neck(th)
    return [x * w, z * w]
  }
  const outline = (n: number): [number, number][] => Array.from({ length: n }, (_v, j) => neck((2 * Math.PI * j) / n))
  let tip = 0
  for (let i = 1; i < pos.length; i += 3) tip = Math.max(tip, pos[i] ?? 0)
  const model: CrownModel = { mesh: { positions: pos, index, groups, colors: col }, tip, neck, surf, outline }
  if (roots) model.roots = rootsMesh(roots, sx, sz, sd, (k, th) => trunkPt(roots, k, 0, th), [c0x, c0z])
  return model
}

/** Сетка корней по таблице: ствол кольцами от шейки (тот же обход, что у формулы
 *  `buildRoots`, — нормали наружу), у однокорневого он сходится в апекс, у
 *  многокорневого закрыт сводом у фуркации; корни — кольцами до апекса. Одна
 *  группа — один материал (дентин). */
function rootsMesh(rs: RootSet, sx: number, sz: number, sd: number,
  trunkPt: (k: number, th: number) => [number, number], c0: [number, number]): RawMesh {
  const pos: number[] = []
  const idx: number[] = []
  /** кольца (rows × n) + вершина, к которой сходится последнее кольцо */
  const rings = (rows: number, n: number, ring: (k: number, j: number) => [number, number, number], tip: [number, number, number]): void => {
    const base = pos.length / 3
    for (let k = 0; k < rows; k++) {
      for (let j = 0; j < n; j++) pos.push(...ring(k, j))
    }
    for (let k = 0; k < rows - 1; k++) {
      for (let j = 0; j < n; j++) {
        const jn = (j + 1) % n
        const a = base + k * n + j
        const b = base + k * n + jn
        const c = base + (k + 1) * n + jn
        const d = base + (k + 1) * n + j
        idx.push(a, b, c, a, c, d)
      }
    }
    const t = pos.length / 3
    pos.push(...tip)
    const o = base + (rows - 1) * n
    for (let j = 0; j < n; j++) idx.push(o + j, o + ((j + 1) % n), t)
  }
  const tr = rs.trunk
  const K = tr.d.length
  const multi = rs.list.length > 0
  const dep = (d: number | undefined): number => -(d ?? 0) * sd
  // однокорневой: последняя строка ствола — апекс (множитель 0), её место занимает
  // вершина; многокорневой: ствол закрыт сводом на 0,3 мм ниже фуркации
  const lastT = multi ? K - 1 : K - 2
  const apexT: [number, number, number] = multi
    ? [c0[0] + (tr.ox[K - 1] ?? 0) * sx, dep((tr.d[K - 1] ?? 0) + 0.3), c0[1] + (tr.oz[K - 1] ?? 0) * sz]
    : (() => { const [x, z] = trunkPt(K - 1, 0); return [x, dep(tr.d[K - 1]), z] as [number, number, number] })()
  rings(lastT + 1, rs.theta, (k, j) => {
    const [x, z] = trunkPt(k, (2 * Math.PI * j) / rs.theta)
    return [x, dep(tr.d[k]), z]
  }, apexT)
  for (const q of rs.list) {
    const L = q.d.length - 1
    rings(L, rs.rt, (k, j) => {
      const a = (2 * Math.PI * j) / rs.rt
      const r = q.r[k]?.[j] ?? 0
      return [((q.cx[k] ?? 0) + r * Math.cos(a)) * sx, dep(q.d[k]), ((q.cz[k] ?? 0) + r * Math.sin(a)) * sz]
    }, [(q.cx[L] ?? 0) * sx, dep(q.d[L]), (q.cz[L] ?? 0) * sz])
  }
  return oneGroup(pos, idx)
}
