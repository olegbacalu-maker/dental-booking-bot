import * as THREE from 'three'
import { SURFACE_ORDER, type SurfaceId } from './surfaces'

/**
 * Процедурная геометрия верхнего первого моляра (зуб 16 по FDI).
 *
 * ⛔ Почему не готовая модель. `vite.config.ts` объявляет `assetFileNames`,
 * который БРОСАЕТ исключение на любой ассет кроме `.css`: маршрут движка
 * `/static/{kind}/{name}` пропускает только css, js и fonts. Любой .glb,
 * импортированный через Vite, уронил бы `npm run build`. Плюс сторонняя
 * dental-модель — это чужая лицензия внутри медицинского продукта. Поэтому
 * коронка считается формулой: ноль байт ассетов, ноль лицензионных вопросов,
 * и любую пропорцию можно поправить числом, а не в блендере.
 *
 * Оси и клинический канон (зуб 16 — верхний ПРАВЫЙ первый моляр):
 *   +x — дистально, −x — медиально,
 *   +z — вестибулярно (щёчно), −z — нёбно (язычно),
 *   +y — окклюзионно (жевательная поверхность смотрит вверх).
 * Коронка занимает y ∈ [0, CROWN_H]; шейка — y = 0; корни уходят вниз.
 *
 * Размеры — средние для 16-го зуба (Wheeler, таблица коронок):
 *   мезио-дистальный диаметр ≈ 10 мм, вестибуло-нёбный ≈ 11 мм,
 *   высота коронки ≈ 7,5 мм, длина корней ≈ 12 мм. 1 единица сцены = 1 мм.
 */

const CROWN_H = 7.6
/** Половина мезио-дистального диаметра (ось x). */
const HALF_MD = 5.0
/** Половина вестибуло-нёбного диаметра (ось z). */
const HALF_BL = 5.5

/** Сегментов по окружности. Кратно 4 — иначе граница секторов попадёт внутрь квада. */
const THETA_SEG = 96
/** Рядов стенки коронки от шейки до краевого гребня. */
const WALL_ROWS = 40
/** Колец жевательной площадки от гребня к центральной ямке. */
const CAP_RINGS = 16

/** Скруглённость поперечника: 2 — эллипс, больше — ближе к прямоугольнику. */
const SQUARENESS = 3.2

/** Доля полудиаметра на уровне краевого гребня (последний узел PROFILE). */
const PROFILE_TOP = 0.90

/** Границы секторов в градусах, θ отсчитывается от +x (дистально) к +z (щёчно). */
const SECTORS: readonly { id: SurfaceId; from: number; to: number }[] = [
  { id: 'distal', from: -30, to: 30 },
  { id: 'buccal', from: 30, to: 150 },
  { id: 'mesial', from: 150, to: 210 },
  { id: 'lingual', from: 210, to: 330 },
]

interface Cusp {
  x: number
  z: number
  h: number
  sx: number
  sz: number
}

/** Четыре бугра моляра: медиально-щёчный, дистально-щёчный, медиально-нёбный
 *  (самый крупный), дистально-нёбный (самый мелкий). Бугорок Карабелли не
 *  моделируем — он есть не у всех и для прототипа поверхностей не нужен. */
const CUSPS: readonly Cusp[] = [
  { x: -2.40, z: 2.80, h: 2.00, sx: 1.80, sz: 1.80 },
  { x: 2.55, z: 2.70, h: 1.78, sx: 1.72, sz: 1.72 },
  { x: -2.50, z: -2.90, h: 1.88, sx: 1.90, sz: 1.90 },
  { x: 2.65, z: -2.50, h: 1.38, sx: 1.62, sz: 1.62 },
]

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

/** Профиль коронки по высоте: шейка сужена, экватор в нижней трети, к
 *  жевательной площадке лёгкое сужение. Узлы — доли от полудиаметра. */
const PROFILE: readonly [number, number][] = [
  [0.0, 0.80],
  [0.16, 0.92],
  [0.34, 1.0],
  [0.62, 0.99],
  [0.86, 0.95],
  [1.0, 0.90],
]

/**
 * Профиль считается сплайном Catmull-Rom, а НЕ кусочной интерполяцией.
 * Кусочная даёт излом производной в каждом узле, а `computeVertexNormals`
 * превращает излом в резкую смену освещения — на модели это читается как
 * кольцевые «обручи» поперёк коронки. Сплайн непрерывен по касательной, и
 * колец нет.
 */
function profileAt(t: number): number {
  const n = PROFILE.length
  let i = 1
  while (i < n - 1) {
    const cur = PROFILE[i]
    if (!cur || t <= cur[0]) break
    i += 1
  }
  const p1 = PROFILE[i - 1]
  const p2 = PROFILE[i]
  if (!p1 || !p2) return 1
  const p0 = PROFILE[i - 2] ?? p1
  const p3 = PROFILE[i + 1] ?? p2
  const span = p2[0] - p1[0]
  const u = span > 0 ? Math.min(1, Math.max(0, (t - p1[0]) / span)) : 0
  const u2 = u * u
  const u3 = u2 * u
  return (
    0.5 *
    ((2 * p1[1]) +
      (-p0[1] + p2[1]) * u +
      (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * u2 +
      (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * u3)
  )
}

/** Высота краевого гребня на угле θ: жевательная площадка не обрывается в
 *  плоское кольцо, край у моляра приподнят. Стенка и площадка используют
 *  ОДНО это значение, поэтому шва между ними нет. */
function marginalRidge(theta: number): number {
  const [rx, rz] = crossSection(theta, HALF_MD * PROFILE_TOP, HALF_BL * PROFILE_TOP)
  return occlusalRelief(rx, rz) * 0.52
}

/** Суперэллипс: точка поперечника на угле θ при полуосях a и b. */
function crossSection(theta: number, a: number, b: number): [number, number] {
  const c = Math.cos(theta)
  const s = Math.sin(theta)
  const p = 2 / SQUARENESS
  const x = Math.sign(c) * Math.pow(Math.abs(c), p) * a
  const z = Math.sign(s) * Math.pow(Math.abs(s), p) * b
  return [x, z]
}

/** Рельеф жевательной площадки над уровнем краевого гребня. */
function occlusalRelief(x: number, z: number): number {
  let h = 0
  for (const c of CUSPS) {
    const dx = (x - c.x) / c.sx
    const dz = (z - c.z) / c.sz
    h += c.h * Math.exp(-0.5 * (dx * dx + dz * dz))
  }
  // Центральная ямка.
  const fx = (x - 0.1) / 1.15
  const fz = z / 1.30
  h -= 1.15 * Math.exp(-0.5 * (fx * fx + fz * fz))
  // Щёчная борозда: уходит от центральной ямки к вестибулярной стороне.
  const gb = Math.exp(-0.5 * Math.pow(x / 0.52, 2))
  h -= 0.70 * gb * Math.min(1, Math.max(0, (z + 0.3) / 1.9))
  // Дистально-нёбная борозда.
  const gd = Math.exp(-0.5 * Math.pow((x - 1.75) / 0.52, 2))
  h -= 0.58 * gd * Math.min(1, Math.max(0, (-z - 0.3) / 1.9))
  return Math.max(0, h)
}

function sectorOf(thetaDeg: number): SurfaceId {
  let d = thetaDeg % 360
  if (d < -30) d += 360
  if (d >= 330) d -= 360
  for (const s of SECTORS) {
    if (d >= s.from && d < s.to) return s.id
  }
  return 'buccal'
}

export interface ToothGeometry {
  /** Коронка: одна геометрия, пять групп в порядке SURFACE_ORDER. */
  crown: THREE.BufferGeometry
  /** faceIndex → индекс поверхности в SURFACE_ORDER. Ключ всего пикинга. */
  faceSurface: Uint8Array
  /** Шейка и три корня. В пикинге не участвуют. */
  roots: THREE.BufferGeometry
  stats: { crownTriangles: number; rootTriangles: number; vertices: number }
}

/**
 * Собирает коронку: стенка (сетка θ × высота) плюс жевательная площадка
 * (полярная сетка от краевого гребня к центру). Кольцо гребня у стенки и у
 * площадки ОБЩЕЕ — иначе `computeVertexNormals` дал бы там шов со стыком
 * освещения. Треугольники раскладываются по пяти спискам и сшиваются в один
 * индекс, чтобы каждая поверхность стала непрерывной группой: тогда у меша
 * ровно пять материалов, а faceIndex однозначно переводится в поверхность.
 */
export function buildToothGeometry(): ToothGeometry {
  const pos: number[] = []

  // --- стенка коронки -------------------------------------------------
  // Индекс вершины стенки: row * THETA_SEG + j.
  for (let row = 0; row <= WALL_ROWS; row += 1) {
    const t = row / WALL_ROWS
    const w = profileAt(t)
    const y = t * CROWN_H
    // У верхних рядов стенка поднимается к краевому гребню.
    const k = smoothstep(0.72, 1.0, t)
    for (let j = 0; j < THETA_SEG; j += 1) {
      const theta = (2 * Math.PI * j) / THETA_SEG
      const [x, z] = crossSection(theta, HALF_MD * w, HALF_BL * w)
      pos.push(x, y + marginalRidge(theta) * k, z)
    }
  }
  const rimStart = WALL_ROWS * THETA_SEG

  // --- жевательная площадка -------------------------------------------
  // Кольца от гребня (s = 1, общие вершины стенки) к центру (s = 0).
  const capRingStart: number[] = [rimStart]
  for (let k = 1; k <= CAP_RINGS; k += 1) {
    const s = 1 - k / CAP_RINGS
    if (k === CAP_RINGS) {
      capRingStart.push(pos.length / 3)
      pos.push(0, CROWN_H + occlusalRelief(0, 0), 0)
      break
    }
    capRingStart.push(pos.length / 3)
    for (let j = 0; j < THETA_SEG; j += 1) {
      const theta = (2 * Math.PI * j) / THETA_SEG
      const [rx, rz] = crossSection(theta, HALF_MD * PROFILE_TOP, HALF_BL * PROFILE_TOP)
      const x = rx * s
      const z = rz * s
      // К самому краю рельеф переходит в краевой гребень — тот же, что у
      // верхнего ряда стенки. Геометрия сходится без ступеньки.
      const fade = 1 - smoothstep(0.70, 1.0, s)
      const ridge = marginalRidge(theta)
      pos.push(x, CROWN_H + occlusalRelief(x, z) * fade + ridge * (1 - fade), z)
    }
  }

  // --- треугольники по поверхностям ------------------------------------
  const buckets = new Map<SurfaceId, number[]>(SURFACE_ORDER.map((id) => [id, []]))
  const push = (id: SurfaceId, a: number, b: number, c: number) => {
    const arr = buckets.get(id)
    if (arr) arr.push(a, b, c)
  }

  const stepDeg = 360 / THETA_SEG
  for (let row = 0; row < WALL_ROWS; row += 1) {
    for (let j = 0; j < THETA_SEG; j += 1) {
      const jn = (j + 1) % THETA_SEG
      const a = row * THETA_SEG + j
      const b = row * THETA_SEG + jn
      const c = (row + 1) * THETA_SEG + jn
      const d = (row + 1) * THETA_SEG + j
      const id = sectorOf((j + 0.5) * stepDeg)
      push(id, a, c, b)
      push(id, a, d, c)
    }
  }

  for (let k = 0; k < CAP_RINGS; k += 1) {
    const outer = capRingStart[k]
    const inner = capRingStart[k + 1]
    if (outer === undefined || inner === undefined) continue
    if (k === CAP_RINGS - 1) {
      for (let j = 0; j < THETA_SEG; j += 1) {
        const jn = (j + 1) % THETA_SEG
        push('occlusal', outer + j, inner, outer + jn)
      }
    } else {
      for (let j = 0; j < THETA_SEG; j += 1) {
        const jn = (j + 1) % THETA_SEG
        push('occlusal', outer + j, inner + j, inner + jn)
        push('occlusal', outer + j, inner + jn, outer + jn)
      }
    }
  }

  const index: number[] = []
  const crown = new THREE.BufferGeometry()
  const faceSurface = new Uint8Array(
    SURFACE_ORDER.reduce((n, id) => n + (buckets.get(id)?.length ?? 0) / 3, 0),
  )
  let face = 0
  SURFACE_ORDER.forEach((id, slot) => {
    const arr = buckets.get(id) ?? []
    crown.addGroup(index.length, arr.length, slot)
    for (let i = 0; i < arr.length; i += 3) {
      faceSurface[face] = slot
      face += 1
    }
    for (const v of arr) index.push(v)
  })

  crown.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  crown.setIndex(index)
  crown.computeVertexNormals()
  crown.computeBoundingSphere()

  const roots = buildRoots()
  const rootIdx = roots.getIndex()

  return {
    crown,
    faceSurface,
    roots,
    stats: {
      crownTriangles: index.length / 3,
      rootTriangles: rootIdx ? rootIdx.count / 3 : 0,
      vertices: pos.length / 3 + (roots.getAttribute('position')?.count ?? 0),
    },
  }
}

interface RootSpec {
  x: number
  z: number
  r: number
  len: number
  outX: number
  outZ: number
}

/** Три корня верхнего моляра: медиально-щёчный, дистально-щёчный и нёбный
 *  (самый длинный). Плюс шеечный переход, чтобы коронка не «висела». */
const ROOTS: readonly RootSpec[] = [
  { x: -1.70, z: 1.70, r: 1.85, len: 11.8, outX: -1.45, outZ: 1.35 },
  { x: 1.80, z: 1.75, r: 1.75, len: 11.2, outX: 1.55, outZ: 1.20 },
  { x: 0.10, z: -2.00, r: 2.10, len: 12.8, outX: 0.10, outZ: -2.40 },
]

const ROOT_SEG = 24
const ROOT_ROWS = 14
/** Высота шеечного перехода вниз от клинической шейки. */
const COLLAR_H = 2.6
const COLLAR_ROWS = 9

function buildRoots(): THREE.BufferGeometry {
  const pos: number[] = []
  const index: number[] = []

  // Шеечный переход: продолжение поперечника коронки вниз с сужением.
  for (let row = 0; row <= COLLAR_ROWS; row += 1) {
    const t = row / COLLAR_ROWS
    const w = profileAt(0) * (1 - 0.14 * smoothstep(0, 1, t))
    const y = -COLLAR_H * t
    for (let j = 0; j < THETA_SEG; j += 1) {
      const theta = (2 * Math.PI * j) / THETA_SEG
      const [x, z] = crossSection(theta, HALF_MD * w, HALF_BL * w)
      pos.push(x, y, z)
    }
  }
  for (let row = 0; row < COLLAR_ROWS; row += 1) {
    for (let j = 0; j < THETA_SEG; j += 1) {
      const jn = (j + 1) % THETA_SEG
      const a = row * THETA_SEG + j
      const b = row * THETA_SEG + jn
      const c = (row + 1) * THETA_SEG + jn
      const d = (row + 1) * THETA_SEG + j
      index.push(a, b, c, a, c, d)
    }
  }

  for (const spec of ROOTS) {
    const base = pos.length / 3
    for (let row = 0; row <= ROOT_ROWS; row += 1) {
      const t = row / ROOT_ROWS
      const y = -COLLAR_H * 0.62 - spec.len * t
      // Корень расходится в сторону и сужается к верхушке.
      const bend = t * t
      const cx = spec.x + spec.outX * bend
      const cz = spec.z + spec.outZ * bend
      const r = spec.r * Math.pow(1 - t, 0.62) * (1 + 0.10 * Math.sin(Math.PI * t))
      if (row === ROOT_ROWS) {
        pos.push(cx, y, cz)
        break
      }
      for (let j = 0; j < ROOT_SEG; j += 1) {
        const theta = (2 * Math.PI * j) / ROOT_SEG
        // Лёгкое уплощение корня в мезио-дистальном направлении.
        pos.push(cx + Math.cos(theta) * r * 0.82, y, cz + Math.sin(theta) * r)
      }
    }
    for (let row = 0; row < ROOT_ROWS; row += 1) {
      const outer = base + row * ROOT_SEG
      const inner = base + (row + 1) * ROOT_SEG
      if (row === ROOT_ROWS - 1) {
        const tip = base + ROOT_ROWS * ROOT_SEG
        for (let j = 0; j < ROOT_SEG; j += 1) {
          const jn = (j + 1) % ROOT_SEG
          index.push(outer + j, outer + jn, tip)
        }
      } else {
        for (let j = 0; j < ROOT_SEG; j += 1) {
          const jn = (j + 1) % ROOT_SEG
          index.push(outer + j, inner + jn, inner + j)
          index.push(outer + j, outer + jn, inner + jn)
        }
      }
    }
  }

  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setIndex(index)
  g.computeVertexNormals()
  g.computeBoundingSphere()
  return g
}
