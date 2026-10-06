import type { Vec3 } from './arch'
import type { RawMesh } from './mesh'
import type { Cls } from './toothGeometry'

/* Десна (06.10, кадры до/после — слово Олега «нравится»): её СТРОЯТ по краю
   у каждого зуба, а не тянут трубкой вдоль дуги, как было до 06.10.

   Как устроена. Вокруг шейки каждого зуба — петля края: высота над шейкой
   задана в восьми опорах (D, DV, V, MV, M, ML, L, DL), между ними — плавная
   косинусная связка; точка петли лежит НА стенке зуба (`surf` той же
   коронки), на 0,04 мм внутри — линия десны выходит чистой, без щели.
   Дальше — «рёбра» поперёк дуги через каждые ~0,3 мм длины дуги: у ребра
   верх (щёчная и язычная точки края, между ними — внутри зуба), щёчный и
   язычный скаты до боковой точки и низ полуэллипсом. Где ребро проходит
   сквозь зуб, верх — пересечение с его петлёй; между зубами — сосочек
   (гребень от крайней точки одного зуба к крайней точке соседа, при
   потерянном сосочке — с провалом); где зуба нет — округлый гребень
   беззубого участка. Рёбра сшиваются в одну сетку — ни швов, ни щелей.

   Данные пародонтограммы сюда приходят только через опоры: рецессия опускает
   опору ниже шейки (h = −REC), потерянный сосочек — проксимальную опору;
   карман глубже порога красит полосу у края (`stripe`, цвета вершин). Ничего
   клинического не считается: пороги и числа — с сервера. */

export type GumKind = 'tooth' | 'pontic' | 'missing' | 'socket'

/** Опоры края по окружности шейки, θ от +x (дистально) к +z (щёчно). */
export const ANCHOR_DEG = [0, 50, 90, 130, 180, 230, 270, 310] as const
const ANCHOR_TH = ANCHOR_DEG.map((d) => (d * Math.PI) / 180)
/** Точки пародонтограммы в порядке сервера (MV V DV ML L DL) → угол на петле. */
export const SITE_DEG = [130, 90, 50, 230, 270, 310] as const
/** Опора → точка сервера (у проксимальных опор M и D своей точки нет). */
const ANCHOR_SITE = [-1, 2, 1, 0, -1, 3, 4, 5] as const

export interface GumTooth {
  n: number
  kind: GumKind
  /** середина зуба на дуге — длина дуги, как `PlacedTooth.s` */
  s: number
  md: number
  bl: number
  /** длина корня, мм (с сервера) — десна обязана быть глубже его верхушки */
  root: number
  position: Vec3
  xAxis: Vec3
  yAxis: Vec3
  zAxis: Vec3
  /** стенка зуба (x, z) на высоте h мм над шейкой */
  surf: (th: number, h: number) => [number, number]
  /** высота края над шейкой в восьми опорах `ANCHOR_DEG`, мм */
  anchors: number[]
  /** цвет полосы кармана в опоре (линейный rgb) или null */
  stripe: (number[] | null)[]
}

export interface GumInput {
  A: number
  D: number
  apex: number
  yBase: number
  /** +1 нижняя челюсть (окклюзионно = +y), −1 верхняя */
  occ: 1 | -1
  teeth: GumTooth[]
}

// ---------------------------------------------------------------- опоры

/** Здоровый край над шейкой, мм: середина щёчной/язычной стороны, угол, сосочек. */
const HEALTHY: Record<Cls, { mid: number; line: number; prox: number }> = {
  incisor_c: { mid: 0.9, line: 2.0, prox: 4.0 },
  incisor_l: { mid: 0.8, line: 1.9, prox: 3.6 },
  canine: { mid: 0.8, line: 1.7, prox: 3.2 },
  premolar: { mid: 0.6, line: 1.4, prox: 2.6 },
  molar: { mid: 0.5, line: 1.1, prox: 2.2 },
}

/** Опоры края: здоровый край или по рецессии (h = −REC). Сосочек у соседа,
 *  которого нет, не стоит — край там низкий; сосочек при рецессии в соседней
 *  точке опускается (тупой сосочек, «чёрный треугольник»). */
export function anchorsFor(cls: Cls, rec: number[] | null, mesialGone: boolean, distalGone: boolean): number[] {
  const hl = HEALTHY[cls]
  const site = (i: number, base: number): number => {
    const r = rec?.[i] ?? 0
    return r > 0 ? -r : base
  }
  const mv = site(0, hl.line)
  const v = site(1, hl.mid)
  const dv = site(2, hl.line)
  const ml = site(3, hl.line)
  const l = site(4, hl.mid)
  const dl = site(5, hl.line)
  const prox = (a: number, b: number, ra: number, rb: number, gone: boolean): number => {
    if (gone) return Math.min(a, b, 0.6)
    if (ra > 0 || rb > 0) return Math.min(a, b) + 0.8
    return hl.prox
  }
  const m = prox(mv, ml, rec?.[0] ?? 0, rec?.[3] ?? 0, mesialGone)
  const d = prox(dv, dl, rec?.[2] ?? 0, rec?.[5] ?? 0, distalGone)
  return [d, dv, v, mv, m, ml, l, dl]
}

/** Полосы в опорах из цвета точек (MV V DV ML L DL); у сосочка — худшая из двух соседних. */
export function stripesFor(sites: (number[] | null)[] | null): (number[] | null)[] {
  if (!sites) return ANCHOR_DEG.map(() => null)
  const worse = (a: number[] | null | undefined, b: number[] | null | undefined): number[] | null => {
    if (!a) return b ?? null
    if (!b) return a
    // красный «тяжелее» жёлтого: меньше зелёного — хуже
    return (a[1] ?? 0) <= (b[1] ?? 0) ? a : b
  }
  return ANCHOR_SITE.map((si, k) => {
    if (si >= 0) return sites[si] ?? null
    return k === 0 ? worse(sites[2], sites[5]) : worse(sites[0], sites[3])
  })
}

const TAU = Math.PI * 2
function seg(th: number): [number, number] {
  let t = th % TAU
  if (t < 0) t += TAU
  let k = ANCHOR_TH.length - 1
  for (let i = 0; i < ANCHOR_TH.length - 1; i++) {
    if (t >= (ANCHOR_TH[i] ?? 0) && t < (ANCHOR_TH[i + 1] ?? TAU)) { k = i; break }
  }
  const a = ANCHOR_TH[k] ?? 0
  const b = k === ANCHOR_TH.length - 1 ? TAU : (ANCHOR_TH[k + 1] ?? TAU)
  const f = (t - a) / (b - a)
  return [k, (1 - Math.cos(Math.PI * f)) / 2]
}

/** Высота края над шейкой под углом θ — косинусная связка опор (без выбросов). */
export function marginH(anchors: number[], th: number): number {
  const [k, w] = seg(th)
  const a = anchors[k] ?? 0
  const b = anchors[(k + 1) % anchors.length] ?? a
  return a + (b - a) * w
}

/** Полоса под углом θ: цвет и непрозрачность (0 — полосы нет). */
export function stripeAt(stripe: (number[] | null)[], th: number): [number[], number] {
  const [k, w] = seg(th)
  const a = stripe[k] ?? null
  const b = stripe[(k + 1) % stripe.length] ?? null
  if (!a && !b) return [[0, 0, 0], 0]
  const ca = a ?? b ?? [0, 0, 0]
  const cb = b ?? a ?? [0, 0, 0]
  const al = (a ? 1 - w : 0) + (b ? w : 0)
  return [ca.map((v, i) => v + ((cb[i] ?? v) - v) * w), al]
}

/** Точка края зуба в пространстве челюсти: стенка под углом θ на высоте края. */
export function marginPoint(t: GumTooth, th: number, out = 0): Vec3 {
  const h = marginH(t.anchors, th)
  return wallPoint(t, th, h, out)
}

/** Точка стенки зуба (x, h, z) → пространство челюсти; `out` — сдвиг наружу, мм. */
export function wallPoint(t: GumTooth, th: number, h: number, out = 0): Vec3 {
  const [lx, lz] = t.surf(th, h)
  const r = Math.hypot(lx, lz)
  const f = r > 0.2 ? (r + out) / r : 1
  const x = lx * f
  const z = lz * f
  return [
    t.position[0] + t.xAxis[0] * x + t.yAxis[0] * h + t.zAxis[0] * z,
    t.position[1] + t.xAxis[1] * x + t.yAxis[1] * h + t.zAxis[1] * z,
    t.position[2] + t.xAxis[2] * x + t.yAxis[2] * h + t.zAxis[2] * z,
  ]
}

// ---------------------------------------------------------------- дуга

interface Frame { x: number; z: number; tx: number; tz: number; nx: number; nz: number }

/** Та же парабола, что у `layoutArch` (z = apex − D·x²/A²), с гладкой
 *  нормалью и продолжением по касательной за концами дуги. */
function archFrame(A: number, D: number, apex: number) {
  const N = 3000
  const xs = new Float64Array(N + 1)
  const ss = new Float64Array(N + 1)
  const zf = (x: number): number => apex - (D * x * x) / (A * A)
  xs[0] = -A
  for (let i = 1; i <= N; i++) {
    const x0 = -A + (2 * A * (i - 1)) / N
    const x1 = -A + (2 * A * i) / N
    xs[i] = x1
    ss[i] = (ss[i - 1] ?? 0) + Math.hypot(x1 - x0, zf(x1) - zf(x0))
  }
  const total = ss[N] ?? 0
  const xAt = (u: number): number => {
    let lo = 0
    let hi = N
    while (hi - lo > 1) {
      const m = (lo + hi) >> 1
      if ((ss[m] ?? 0) <= u) lo = m
      else hi = m
    }
    const f = (u - (ss[lo] ?? 0)) / (((ss[hi] ?? 0) - (ss[lo] ?? 0)) || 1)
    return (xs[lo] ?? 0) + ((xs[hi] ?? 0) - (xs[lo] ?? 0)) * f
  }
  const at = (u: number): Frame => {
    const uu = Math.max(0, Math.min(total, u))
    const x = xAt(uu)
    const dz = (-2 * D * x) / (A * A)
    const L = Math.hypot(1, dz)
    const tx = 1 / L
    const tz = dz / L
    let px = x
    let pz = zf(x)
    const over = u < 0 ? u : u > total ? u - total : 0
    px += tx * over
    pz += tz * over
    return { x: px, z: pz, tx, tz, nx: -tz, nz: tx }
  }
  const kappa = (u: number): number => {
    if (u < 0 || u > total) return 0
    const x = xAt(u)
    const d1 = (-2 * D * x) / (A * A)
    return ((2 * D) / (A * A)) / Math.pow(1 + d1 * d1, 1.5)
  }
  /** Станция точки: u, при котором точка лежит в нормальной плоскости дуги. */
  const project = (px: number, pz: number, guess: number): number => {
    let u = guess
    for (let it = 0; it < 40; it++) {
      const f = at(u)
      const g = (px - f.x) * f.tx + (pz - f.z) * f.tz
      if (Math.abs(g) < 1e-7) break
      const w = (px - f.x) * f.nx + (pz - f.z) * f.nz
      const d = 1 + kappa(u) * w
      u += g / (d > 0.2 ? d : 0.2)
    }
    return u
  }
  return { total, at, project }
}

// ---------------------------------------------------------------- петли

interface Loop {
  tooth: GumTooth
  u0: number
  u: number[]
  w: number[]
  v: number[]
  /** полоса на петле: r g b a */
  sc: number[][]
  uMin: number
  uMax: number
  iMin: number
  iMax: number
}

const K = 144

function marginLoop(t: GumTooth, F: ReturnType<typeof archFrame>, yBase: number, occ: number): Loop {
  const u0 = F.project(t.position[0], t.position[2], t.s)
  const f0 = F.at(u0)
  const u: number[] = []
  const w: number[] = []
  const v: number[] = []
  const sc: number[][] = []
  for (let k = 0; k < K; k++) {
    const th = (TAU * k) / K
    const P = marginPoint(t, th, -0.04)
    const guess = u0 + (P[0] - t.position[0]) * f0.tx + (P[2] - t.position[2]) * f0.tz
    const uk = F.project(P[0], P[2], guess)
    const fr = F.at(uk)
    u.push(uk)
    w.push((P[0] - fr.x) * fr.nx + (P[2] - fr.z) * fr.nz)
    v.push((P[1] - yBase) * occ)
    const [c, a] = stripeAt(t.stripe, th)
    sc.push([c[0] ?? 0, c[1] ?? 0, c[2] ?? 0, a])
  }
  let iMin = 0
  let iMax = 0
  for (let k = 1; k < K; k++) {
    if ((u[k] ?? 0) < (u[iMin] ?? 0)) iMin = k
    if ((u[k] ?? 0) > (u[iMax] ?? 0)) iMax = k
  }
  return { tooth: t, u0, u, w, v, sc, uMin: u[iMin] ?? u0, uMax: u[iMax] ?? u0, iMin, iMax }
}

interface TopPt { w: number; v: number; c: number[] }

/** Щёчная и язычная точки края на станции u (пересечение ребра с петлёй). */
function cut(L: Loop, uq: number): [TopPt, TopPt] {
  const hits: TopPt[] = []
  for (let k = 0; k < K; k++) {
    const k2 = (k + 1) % K
    const a = L.u[k] ?? 0
    const b = L.u[k2] ?? 0
    if ((a - uq) * (b - uq) > 0 || a === b) continue
    const f = (uq - a) / (b - a)
    const ca = L.sc[k] ?? [0, 0, 0, 0]
    const cb = L.sc[k2] ?? ca
    hits.push({
      w: (L.w[k] ?? 0) + ((L.w[k2] ?? 0) - (L.w[k] ?? 0)) * f,
      v: (L.v[k] ?? 0) + ((L.v[k2] ?? 0) - (L.v[k] ?? 0)) * f,
      c: ca.map((x, i) => x + ((cb[i] ?? x) - x) * f),
    })
  }
  if (hits.length < 2) {
    const i = uq - L.uMin < L.uMax - uq ? L.iMin : L.iMax
    const p = { w: L.w[i] ?? 0, v: L.v[i] ?? 0, c: L.sc[i] ?? [0, 0, 0, 0] }
    return [p, p]
  }
  let bu = hits[0] as TopPt
  let li = hits[0] as TopPt
  for (const h of hits) {
    if (h.w > bu.w) bu = h
    if (h.w < li.w) li = h
  }
  return [bu, li]
}

function extreme(L: Loop, max: boolean): TopPt {
  const i = max ? L.iMax : L.iMin
  return { w: L.w[i] ?? 0, v: L.v[i] ?? 0, c: L.sc[i] ?? [0, 0, 0, 0] }
}

// ---------------------------------------------------------------- цвета

const lin = (c: number): number => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
const rgb = (hex: number): number[] => [(hex >> 16) & 255, (hex >> 8) & 255, hex & 255].map((x) => lin(x / 255))
/** Свободная десна у края, прикреплённая, слизистая, низ. */
export const GUM = { top: rgb(0xf2aca4), att: rgb(0xe6918e), muc: rgb(0xca5f68), deep: rgb(0xb0505c) }
export const linRgb = rgb
const mix = (a: number[], b: number[], k: number): number[] => a.map((x, i) => x + ((b[i] ?? x) - x) * k)
const smooth = (e0: number, e1: number, x: number): number => {
  const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)))
  return t * t * (3 - 2 * t)
}
/** Гладкие max/min: обычные дают излом там, где ветки меняются местами, — на
 *  десне это вертикальный шов от края до низа, видный на крупном плане. */
const smax = (a: number, b: number, k = 0.6): number => (a + b + Math.sqrt((a - b) * (a - b) + k * k)) / 2
const smin = (a: number, b: number, k = 0.6): number => (a + b - Math.sqrt((a - b) * (a - b) + k * k)) / 2
function natural(tau: number): number[] {
  if (tau < 0.3) return mix(GUM.top, GUM.att, smooth(0.04, 0.3, tau))
  return mix(GUM.att, GUM.muc, smooth(0.45, 0.95, tau))
}
/** Полоса кармана поверх цвета десны: сильнее у самого края, гаснет за ~1 мм. */
const withStripe = (base: number[], c: number[], k: number): number[] => mix(base, [c[0] ?? 0, c[1] ?? 0, c[2] ?? 0], (c[3] ?? 0) * k)

// ---------------------------------------------------------------- сборка

const NS = 10 // точек ската от края до боковой точки
const NF = 3 // из них — свободная десна у края
const NB = 9 // точек низа между боковыми
const EXT = 4.5 // десна за последним зубом, мм

export function buildGum(inp: GumInput): RawMesh {
  const F = archFrame(inp.A, inp.D, inp.apex)
  const { yBase, occ } = inp
  const loops: Loop[] = []
  const order = new Map<number, number>()
  inp.teeth.forEach((t, i) => order.set(t.n, i))
  for (const t of inp.teeth) if (t.kind === 'tooth') loops.push(marginLoop(t, F, yBase, occ))
  loops.sort((a, b) => a.u0 - b.u0)

  // шейка каждого зуба (и отсутствующего) в высоте челюсти — опора беззубого гребня
  const neckV = inp.teeth.map((t) => ({ t, u: F.project(t.position[0], t.position[2], t.s), v: (t.position[1] - yBase) * occ }))

  // станции: ровная сетка + крайние точки петель со сгущением
  const st: number[] = []
  for (let u = -EXT; u <= F.total + EXT + 1e-9; u += 0.3) st.push(u)
  for (const L of loops) {
    for (const d of [0, 0.05, 0.15, 0.35]) {
      st.push(L.uMin + d, L.uMax - d)
    }
  }
  st.sort((a, b) => a - b)
  const stations: number[] = []
  for (const u of st) {
    if (u < -EXT || u > F.total + EXT) continue
    if (!stations.length || u - (stations[stations.length - 1] ?? 0) > 0.02) stations.push(u)
  }

  const crestOf = (u: number): { v: number; W: number; flat: number } => {
    // ближайший беззубый зуб под станцией; за концом дуги — спуск от последнего зуба
    let best: { t: GumTooth; u: number; v: number } | null = null
    let dist = Infinity
    for (const x of neckV) {
      if (x.t.kind === 'tooth') continue
      const d = Math.abs(u - x.u)
      if (d < dist) { dist = d; best = x }
    }
    if (best && dist <= best.t.md / 2 + 0.6) {
      const k = best.t.kind
      const off = k === 'socket' ? 0.0 : k === 'pontic' ? 0.15 : -0.4
      const W = (k === 'socket' ? 0.88 : k === 'pontic' ? 0.7 : 0.62) * best.t.bl
      return { v: best.v + off, W, flat: k === 'socket' ? 1 : 0.4 }
    }
    // конец дуги: ближайший зуб любой
    let near = neckV[0]
    let dn = Infinity
    for (const x of neckV) {
      const d = Math.abs(u - x.u)
      if (d < dn) { dn = d; near = x }
    }
    const bl = near?.t.bl ?? 9
    return { v: (near?.v ?? 0) - 0.4 - 0.25 * Math.max(0, dn - (near?.t.md ?? 8) / 2), W: 0.6 * bl, flat: 0.3 }
  }
  const widthAt = (u: number): number => {
    let sw = 0
    let s = 0
    for (const x of neckV) {
      const g = Math.exp(-(((u - x.u) / 3.5) ** 2))
      sw += g
      s += g * (0.4 * x.t.bl + 1.9)
    }
    return sw > 1e-6 ? s / sw : 6
  }

  /** глубина низа десны под станцией: ниже верхушек корней соседних зубов на 1,2 мм, не мельче 16 мм */
  // ⚠️ одна глубина на всю челюсть: местная (под каждым корнем) давала волнистый низ —
  // кость челюсти гладкая, бугор над корнем клыка — дело щёчной стороны, а не низа
  let jawDepth = 16
  for (const x of neckV) jawDepth = Math.max(jawDepth, -(x.v - 1.5 - 1.05 * x.t.root) + 1.8)
  const depthAt = (): number => jawDepth
  // B + щёчный скат + SB + низ + SL + язычный скат + L + M1 C M2
  const M = 1 + (NS - 1) + 1 + NB + 1 + (NS - 1) + 1 + 3
  const pos: number[] = []
  const col: number[] = []
  const R = 1.6 // длина перехода от зуба к беззубому гребню
  interface Rib { u: number; B: TopPt; L: TopPt; mid: TopPt[]; crestness: number; face: boolean }

  // --- проход 1: верх каждого ребра — B (щёчно), M1 C M2, L (язычно) в координатах (w, v)
  const ribs: Rib[] = stations.map((u) => {
    const inside = loops.filter((L) => u >= L.uMin - 1e-9 && u <= L.uMax + 1e-9)
    if (inside.length) {
      const L = inside.reduce((a, b) => (Math.abs(u - a.u0) <= Math.abs(u - b.u0) ? a : b))
      const [B, Lp] = cut(L, u)
      const mid = [0.25, 0.5, 0.75].map((f) => ({
        w: Lp.w + (B.w - Lp.w) * f, v: Lp.v + (B.v - Lp.v) * f, c: Lp.c.map((x, i) => x + ((B.c[i] ?? x) - x) * f),
      }))
      // «лицо» зуба — середина щёчной/язычной стороны: по ней строится огибающая скатов
      return { u, B, L: Lp, mid, crestness: 0, face: Math.abs(u - L.u0) < 0.3 * L.tooth.md }
    }
    const left = [...loops].reverse().find((L) => L.uMax < u) ?? null
    const right = loops.find((L) => L.uMin > u) ?? null
    const adjacent = left && right
      && Math.abs((order.get(right.tooth.n) ?? 0) - (order.get(left.tooth.n) ?? 0)) === 1
    if (left && right && adjacent) {
      // сосочек: гребень от крайней точки одного зуба к крайней точке соседа
      const pa = extreme(left, true)
      const pb = extreme(right, false)
      const span = right.uMin - left.uMax
      const f = span > 1e-6 ? (u - left.uMax) / span : 0.5
      const dip = Math.min(1.6, Math.max(0, span - 0.8) * 0.35) * Math.sin(Math.PI * f)
      const q: TopPt = {
        w: pa.w + (pb.w - pa.w) * f,
        v: pa.v + (pb.v - pa.v) * f - dip,
        c: pa.c.map((x, i) => (i < 3 ? x + ((pb.c[i] ?? x) - x) * f : Math.max(x, pb.c[i] ?? 0))),
      }
      return { u, B: q, L: q, mid: [q, q, q], crestness: 0, face: false }
    }
    // беззубый участок или конец дуги: округлый гребень, у зуба сходится в его крайнюю точку
    const cr = crestOf(u)
    let v = cr.v
    let W = cr.W
    let wc = 0
    let c: number[] = [0, 0, 0, 0]
    let k = 1
    if (left) {
      const pa = extreme(left, true)
      const kk = smooth(left.uMax, left.uMax + R, u)
      if (kk < 1) { v = pa.v + (v - pa.v) * kk; W *= kk; wc = pa.w * (1 - kk); c = pa.c.map((x, i) => (i === 3 ? x * (1 - kk) : x)); k = Math.min(k, kk) }
    }
    if (right) {
      const pb = extreme(right, false)
      const kk = smooth(right.uMin, right.uMin - R, u)
      if (kk < 1) { v = pb.v + (v - pb.v) * kk; W *= kk; wc = pb.w * (1 - kk) + wc * kk; c = pb.c.map((x, i) => (i === 3 ? x * (1 - kk) : x)); k = Math.min(k, kk) }
    }
    const drop = (1 - cr.flat) * Math.min(1, W / 3) * 0.9
    return {
      u, crestness: k, face: false,
      B: { w: wc + W / 2, v: v - drop, c },
      L: { w: wc - W / 2, v: v - drop, c },
      mid: [{ w: wc - W / 4, v: v - drop * 0.25, c }, { w: wc, v, c }, { w: wc + W / 4, v: v - drop * 0.25, c }],
    }
  })

  // --- проход 2: огибающая по серединам зубов. Ниже края скат идёт по ней, а не от
  // верхней точки ребра: иначе у каждого сосочка скат уходил бы внутрь до самого низа,
  // и десна вышла бы «шторой» с вертикальными складками.
  const env = (val: (r: Rib) => number, fb: (r: Rib) => number): number[] => ribs.map((r) => {
    let sw = 0
    let s = 0
    for (const q of ribs) {
      if (!q.face) continue
      const d = q.u - r.u
      if (d > 7 || d < -7) continue
      const g = Math.exp(-((d / 2.2) ** 2))
      sw += g
      s += g * val(q)
    }
    return sw > 0.05 ? s / sw : fb(r)
  })
  const eB = env((r) => r.B.w, (r) => r.B.w + 0.4)
  const eL = env((r) => -r.L.w, (r) => -r.L.w + 0.4)
  const vB = env((r) => r.B.v, (r) => r.B.v - 0.6)
  const vL = env((r) => r.L.v, (r) => r.L.v - 0.6)

  // --- проход 3: скаты, низ, цвета
  ribs.forEach((rb, ri) => {
    const { u, B, L: Lp, mid, crestness } = rb
    const EB = smax((eB[ri] ?? 0) + 0.75, B.w + 0.45)
    const EL = smax((eL[ri] ?? 0) + 0.75, -Lp.w + 0.45)
    const vAB = smin((vB[ri] ?? 0) - 0.5, B.v - 0.3)
    const vAL = smin((vL[ri] ?? 0) - 0.5, Lp.v - 0.3)
    const vS = smin(-8, smin(vAB, vAL) - 3, 1)
    const Wb = widthAt(u)
    const Wo = smax(Wb, EB + 0.8)
    const Wi = smax(Wb, EL + 0.8)
    /** скат одной стороны в положительных w: свободная десна от края до огибающей, дальше прикреплённая до боковой точки */
    const sheet = (w0: number, v0: number, E: number, vA: number, W: number): [number, number][] => {
      const out: [number, number][] = []
      // свободная десна: три ряда от края до начала прикреплённой (у каждого ребра своя высота)
      for (let k = 1; k <= NF; k++) {
        const f = k / (NF + 1)
        out.push([w0 + (E - w0) * (1 - (1 - f) * (1 - f)), v0 - (v0 - vA) * f])
      }
      // прикреплённая: ряды на ОДНИХ долях между vA и vS у всех рёбер — без перекоса четырёхугольников
      const na = NS - 1 - NF
      for (let k = 0; k < na; k++) {
        const f2 = Math.pow(k / na, 1.25)
        out.push([E + (W - E) * smooth(0, 1, f2) + 0.35 * Math.sin(Math.PI * f2), vA - (vA - vS) * f2])
      }
      return out
    }
    const buc = sheet(B.w, B.v, EB, vAB, Wo)
    const lng = sheet(-Lp.w, Lp.v, EL, vAL, Wi).map(([w, v]) => [-w, v] as [number, number])
    const wc0 = (Wo - Wi) / 2
    const rw = (Wo + Wi) / 2
    const rv = Math.max(6, depthAt() + vS)
    const bottom: [number, number][] = []
    for (let k = 1; k <= NB; k++) {
      const ph = (Math.PI * k) / (NB + 1)
      bottom.push([wc0 + rw * Math.cos(ph), vS - rv * Math.sin(ph)])
    }

    // --- ребро по кругу: B → щёчный скат → низ → язычный скат (вверх) → L → M1 C M2
    const fr = F.at(u)
    // за последним зубом десна скругляется к торцу, а не обрывается цилиндром
    const over = u < 0 ? -u : u > F.total ? u - F.total : 0
    const q = 1 - 0.55 * (over / EXT) ** 2
    const vMid = (B.v + vS - rv) / 2
    const put = (w0: number, v0: number, c: number[]): void => {
      const w = w0 * q
      const v = vMid + (v0 - vMid) * (0.35 + 0.65 * q)
      pos.push(fr.x + fr.nx * w, yBase + occ * v, fr.z + fr.nz * w)
      col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
    }
    const topCol = mix(GUM.top, GUM.att, crestness * 0.6)
    put(B.w, B.v, withStripe(topCol, B.c, 0.92))
    // полоса кармана — по РАССТОЯНИЮ от края (мм), а не по рядам: у середины зуба
    // свободная десна занимает полмиллиметра, и полоса по рядам была бы не видна
    const band = (d: number): number => 0.92 * Math.exp(-((d / 1.5) ** 2))
    buc.forEach(([w, v], i) => {
      const tau = Math.pow((i + 1) / NS, 1.6)
      put(w, v, withStripe(natural(tau), B.c, band(B.v - v)))
    })
    put(Wo, vS, GUM.muc)
    bottom.forEach(([w, v], i) => put(w, v, mix(GUM.muc, GUM.deep, Math.sin((Math.PI * (i + 1)) / (NB + 1)))))
    put(-Wi, vS, GUM.muc)
    for (let i = lng.length - 1; i >= 0; i--) {
      const p = lng[i] as [number, number]
      const tau = Math.pow((i + 1) / NS, 1.6)
      put(p[0], p[1], withStripe(natural(tau), Lp.c, band(Lp.v - p[1])))
    }
    put(Lp.w, Lp.v, withStripe(topCol, Lp.c, 0.92))
    for (const m of mid) put(m.w, m.v, withStripe(topCol, m.c, 0.6))
  })

  if (pos.length / 3 !== ribs.length * M) throw new Error(`gum: ${pos.length / 3} вершин на ${ribs.length} рёбер по ${M}`)
  // --- сшивка рёбер и торцы
  const idx: number[] = []
  const nR = stations.length
  // обход рёбер даёт нормаль внутрь у нижней челюсти (проверено `gum.proto.test`); у верхней v смотрит вниз — зеркально
  const flip = occ === 1
  for (let i = 0; i < nR - 1; i++) {
    for (let j = 0; j < M; j++) {
      const jn = (j + 1) % M
      const a = i * M + j
      const b = i * M + jn
      const c = (i + 1) * M + jn
      const d = (i + 1) * M + j
      if (flip) idx.push(a, b, c, a, c, d)
      else idx.push(a, c, b, a, d, c)
    }
  }
  for (const ring of [0, nR - 1]) {
    const c0 = pos.length / 3
    let cx = 0
    let cy = 0
    let cz = 0
    for (let j = 0; j < M; j++) {
      cx += pos[(ring * M + j) * 3] ?? 0
      cy += pos[(ring * M + j) * 3 + 1] ?? 0
      cz += pos[(ring * M + j) * 3 + 2] ?? 0
    }
    pos.push(cx / M, cy / M, cz / M)
    col.push(...GUM.muc)
    for (let j = 0; j < M; j++) {
      const jn = (j + 1) % M
      const front = ring === 0
      if (front !== flip) idx.push(c0, ring * M + jn, ring * M + j)
      else idx.push(c0, ring * M + j, ring * M + jn)
    }
  }
  return { positions: pos, index: idx, groups: [{ start: 0, count: idx.length, materialIndex: 0 }], colors: col }
}
