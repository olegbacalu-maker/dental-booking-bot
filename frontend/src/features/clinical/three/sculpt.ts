import type { CrownInput, CrownModel } from './crown'
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
}

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

export function sculptModel(tab: SculptTable, g: CrownInput): CrownModel {
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
  const surf = (th: number, h: number): [number, number] => {
    if (h >= 0) return wallAt(th, Math.min(h / sy, tab.hCap))
    // корень — то же правило, что у `buildRoots`: сечение шейки сужается к корню
    const d = -h
    const w = d <= 2.4 ? 1 - 0.14 * smooth(0, 2.4, d) : Math.max(0.7, 0.86 - 0.03 * (d - 2.4))
    const [x, z] = neck(th)
    return [x * w, z * w]
  }
  const outline = (n: number): [number, number][] => Array.from({ length: n }, (_v, j) => neck((2 * Math.PI * j) / n))
  let tip = 0
  for (let i = 1; i < pos.length; i += 3) tip = Math.max(tip, pos[i] ?? 0)
  return { mesh: { positions: pos, index, groups, colors: col }, tip, neck, surf, outline }
}
