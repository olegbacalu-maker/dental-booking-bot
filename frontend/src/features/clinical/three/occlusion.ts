import type { Vec3 } from './arch'

/* Прикус в 3D (волна «ocluzie», этап 1; задание — `docs/dentpilot-2/ocluzie-3d.md`):
   запись формы «Ocluzia» → поза НИЖНЕЙ челюсти целиком (сдвиг x/y/z, поворот
   вокруг вертикали `yaw` и поперечной оси `pitch` с опорой у моляров). Чистые
   числа, без React и без three, как `arch.ts` / `pose.ts`: сцена отдаёт точки
   коронок, модуль меряет прикус (`Bite`) и отвечает позой.

   Правила, которые ломаются молча:
   - пусто = «не записано», а не «норма» (`ocluzie.py`): пустая запись даёт
     `ZERO_POSE`, модель стоит как стоит, выводов нет;
   - класс 'III' проверяется РАНЬШЕ `startsWith('II')` — в прототипе 06.11
     обратный порядок превращал III в II;
   - класс по Энглю — по ОРИЕНТИРАМ (AAPD, PMC3481985; Олег 07.11):
     мезиально-щёчный бугор верхнего первого моляра против щёчной борозды
     нижнего. I — совпадают, II — бугор мезиальнее борозды, III — дистальнее.
     Фиксированного числа мм у класса нет: `CLASS_SHIFT` — схема, пока
     величину не дала запись (`mmR`/`mmL`);
   - поза — ОДНА формула и для сцены (`placeJaws`), и для замера (`poseLower`):
     поворот R = Ry(yaw)·Rx(pitch) (порядок three 'YXZ') вокруг опоры
     P = (0, pivotY, pivotZ) после сдвига t = (dx, y0 + dy, dz):
     точка челюсти q уходит в P + R·(q + t − P).

   Оси мира сцены: x — поперёк (левая сторона пациента = +x), y — вверх,
   z — вперёд (резцы спереди, моляры при z ≈ −28…−30). */

/** Запись формы — строками, как приходит с сервера (`db.ocluzie`). */
export interface OcclRecord {
  angle_dr?: string
  angle_st?: string
  /** ⚠️ Поля в форме НЕТ (07.11, откуда брать мм — решает Олег): насколько
   *  бугор впереди/позади борозды справа и слева, мм. Нет — `CLASS_SHIFT`. */
  mmR?: string
  mmL?: string
  overjet?: string
  overbite?: string
  incrucisata?: string
  deschisa?: string
  mediana_mm?: string
  mediana_spre?: string
}

/** Поза нижней челюсти, мм и радианы; опора поворота — (0, pivotY, pivotZ) в мире. */
export interface JawPose {
  dx: number
  dy: number
  dz: number
  yaw: number
  pitch: number
  pivotY: number
  pivotZ: number
}

export const ZERO_POSE: Readonly<JawPose> = Object.freeze({ dx: 0, dy: 0, dz: 0, yaw: 0, pitch: 0, pivotY: 0, pivotZ: 0 })

/** Прикус модели, мм: overjet, overbite и где мезиально-щёчный бугор 16/26
 *  относительно щёчной борозды 46/36 по z (`relR` — правая сторона, `relL` —
 *  левая; > 0 — бугор впереди, то есть настолько сдвинуть нижнюю вперёд до I класса).
 *  `byMarks` — мерено по ориентирам коронок; false — по центрам с `REL_I`. */
export interface Bite {
  oj: number
  ob: number
  relR: number
  relL: number
  byMarks?: boolean
}

/** Что нужно из раскладки: z губной поверхности 41 у края, z и полуширина
 *  дуги по точкам замера класса нижних первых моляров (борозды 46/36, без них —
 *  центры): по ним решается поворот вокруг вертикали, z46 — ещё и опора наклона. */
export interface OcclGeo {
  z41: number
  z46: number
  half: number
}

/** Сдвиг моляров при II и III классе, мм — СХЕМАТИЧЕСКОЕ значение (между
 *  половиной и целым бугром), не клиническое: у класса нет своего числа мм,
 *  величина измеряется у пациента (`mmR`/`mmL`). Одно имя на модуль. */
export const CLASS_SHIFT = 4
/** Запасной путь, когда ориентиров нет (коронки-формулы без бугров): бугор
 *  относительно борозды ≈ «центр 16 − центр 46» + REL_I. Замер своих моделей
 *  07.11.2026 — 1,30 мм (`arch.test.ts` › «ориентиры»); прототип 06.11 брал 2. */
export const REL_I = 1.3
/** Открытый прикус без записанного overbite — столько и показываем, мм. */
export const OPEN_OB = -3
/** Полоса от режущего края, в которой ищется губная поверхность резца, мм. */
export const EDGE_BAND = 1.5

/** Направление сдвига нижней челюсти по классу Энгля: I → 0, III → вперёд (+1),
 *  II/1 и II/2 → назад (−1). ⚠️ 'III' — раньше `startsWith('II')`. Незнакомое — как пустое. */
export function classSign(a: string): -1 | 0 | 1 | null {
  if (a === 'I') return 0
  if (a === 'III') return 1
  if (a.startsWith('II')) return -1
  return null
}

/** Миллиметры строкой («3», «3,5», «-2») → число; пусто или мусор → null. */
export function mmOf(v: string | undefined): number | null {
  const s = (v ?? '').trim().replace(',', '.')
  if (!s) return null
  const x = Number(s)
  return Number.isFinite(x) ? x : null
}

/** Шагов секущей для наклона открытого прикуса (поворот не линеен). */
const OPEN_STEPS = 4

/** Запись → поза. `probe(pose)` — overbite модели при такой позе (замер сцены
 *  или `biteAt`); без него наклон открытого прикуса — первое приближение. */
export function jawPose(rec: OcclRecord, base: Bite, geo: OcclGeo, probe?: (p: JawPose) => number): JawPose {
  const pose: JawPose = { ...ZERO_POSE }
  const t = (v: string | undefined): string => (v ?? '').trim()
  const side = (angle: string | undefined, mm: string | undefined, rel: number): number | null => {
    const k = classSign(t(angle))
    if (k === null) return null
    return rel + k * Math.abs(mmOf(mm) ?? CLASS_SHIFT)
  }
  const dzR = side(rec.angle_dr, rec.mmR, base.relR)
  const dzL = side(rec.angle_st, rec.mmL, base.relL)
  const overjet = mmOf(rec.overjet)
  const overbite = mmOf(rec.overbite)
  const open = t(rec.deschisa) !== ''
  // опора: у моляров при открытом прикусе (наклон), иначе (0, 0, 0) — у резцов,
  // поворот вокруг вертикали тогда не трогает записанную среднюю линию
  if (open) pose.pivotZ = geo.z46
  if (dzR !== null || dzL !== null) {
    const r = dzR ?? (dzL as number)
    const l = dzL ?? (dzR as number)
    // правая сторона пациента — −x; точно, а не первым порядком: разные классы
    // сторон дают до 8 мм разницы. Моляр q = (∓half, ·, z46) уходит по z в
    // ±half·sin(yaw) + (z46 + dz − P)·cos(yaw) + P — решаем на r и l.
    const s = geo.half > 0 ? Math.max(-1, Math.min(1, (r - l) / (2 * geo.half))) : 0
    pose.yaw = Math.asin(s)
    const arm = geo.z46 - pose.pivotZ
    pose.dz = (arm + (r + l) / 2) / Math.cos(pose.yaw) - arm
  } else if (overjet !== null) {
    pose.dz = base.oj - overjet
  }
  if (open) {
    // открытый прикус: передний отрезок опускается поворотом вокруг моляров
    const want = overbite ?? OPEN_OB
    const lever = geo.z41 - geo.z46
    pose.pitch = lever > 0 ? Math.atan2(base.ob - want, lever) : 0
    if (probe) {
      // секущая через (0, ob при нулевом наклоне): 2–3 шага доводят до ±0,01 мм
      const ob0 = probe({ ...pose, pitch: 0 })
      for (let i = 0; i < OPEN_STEPS; i++) {
        const got = probe(pose)
        if (Math.abs(got - want) < 0.005 || Math.abs(ob0 - got) < 1e-9) break
        pose.pitch *= (ob0 - want) / (ob0 - got)
      }
    }
  } else if (overbite !== null) {
    pose.dy = overbite - base.ob
  }
  const mm = mmOf(rec.mediana_mm)
  const toward = t(rec.mediana_spre)
  if (mm !== null) pose.dx = toward === 'stanga' ? mm : toward === 'dreapta' ? -mm : 0
  return pose
}

/** Точка нижней челюсти (в её группе) → мир при позе и подъёме группы y0:
 *  P + R·(q + t − P), R = Ry(yaw)·Rx(pitch). Та же формула, что `placeJaws`. */
export function poseLower(q: Vec3, pose: JawPose, y0: number): Vec3 {
  const x = q[0] + pose.dx
  const y = q[1] + y0 + pose.dy - pose.pivotY
  const z = q[2] + pose.dz - pose.pivotZ
  const cp = Math.cos(pose.pitch)
  const sp = Math.sin(pose.pitch)
  const y1 = y * cp - z * sp
  const z1 = y * sp + z * cp
  const cy = Math.cos(pose.yaw)
  const sy = Math.sin(pose.yaw)
  return [x * cy + z1 * sy, y1 + pose.pivotY, -x * sy + z1 * cy + pose.pivotZ]
}

/** Режущий край резца по точкам коронки в мире (плоский массив xyz): `edgeY` —
 *  нижняя точка у верхнего зуба, верхняя у нижнего; `frontZ` — самая губная
 *  точка в полосе `band` от края. */
export function incisal(pts: ArrayLike<number>, upper: boolean, band = EDGE_BAND): { edgeY: number; frontZ: number } {
  let edge = upper ? Infinity : -Infinity
  for (let i = 1; i < pts.length; i += 3) {
    const y = pts[i] as number
    edge = upper ? Math.min(edge, y) : Math.max(edge, y)
  }
  let front = -Infinity
  for (let i = 0; i + 2 < pts.length; i += 3) {
    const y = pts[i + 1] as number
    if (Math.abs(y - edge) <= band) front = Math.max(front, pts[i + 2] as number)
  }
  return { edgeY: edge, frontZ: front }
}

/** Профиль щёчного края коронки моляра в СИСТЕМЕ ЗУБА (x — дистально, y —
 *  окклюзионно, z — щёчно; одна сетка на все квадранты, мезиальная сторона
 *  всегда −x): высшая точка в каждой полосе 0,25 мм по x среди точек щёчной
 *  трети (z выше 0,35 наибольшего). */
function buccalCrest(local: ArrayLike<number>): [number, Vec3][] {
  let zmax = 0
  for (let i = 2; i < local.length; i += 3) zmax = Math.max(zmax, local[i] as number)
  const bins = new Map<number, Vec3>()
  for (let i = 0; i + 2 < local.length; i += 3) {
    const v: Vec3 = [local[i] as number, local[i + 1] as number, local[i + 2] as number]
    if (v[2] <= zmax * 0.35) continue
    const k = Math.round(v[0] * 4) / 4
    const o = bins.get(k)
    if (!o || v[1] > o[1]) bins.set(k, v)
  }
  return [...bins].sort((a, b) => a[0] - b[0])
}

const highest = (row: [number, Vec3][], a: number, b: number): Vec3 | null =>
  row.filter(([k]) => k > a && k < b).map(([, v]) => v).reduce<Vec3 | null>((m, v) => (!m || v[1] > m[1] ? v : m), null)

/** Ориентир первого моляра для класса по Энглю, в системе зуба: у верхнего —
 *  вершина мезиально-щёчного бугра (высшая точка щёчного края с мезиальной
 *  стороны), у нижнего — щёчная борозда (низшая точка края между медиально- и
 *  дистально-щёчным буграми). null — рельефа нет (коронка-формула, обломок):
 *  тогда замер идёт по центрам с `REL_I`. `md` — ширина коронки, мм. */
export function molarMark(local: ArrayLike<number>, md: number, upper: boolean): Vec3 | null {
  const row = buccalCrest(local)
  if (upper) {
    const cusp = highest(row, -md, 0)
    const db = highest(row, 0, md)
    // бугор — настоящий: между ним и дистально-щёчным край опускается
    if (!cusp || !db) return null
    const dip = row.filter(([k]) => k > cusp[0] && k < db[0]).reduce((m, [, v]) => Math.min(m, v[1]), Infinity)
    return cusp[1] - dip > 0.1 && db[1] - dip > 0.1 ? cusp : null
  }
  const mb = highest(row, -md, -0.2 * md)
  const db = highest(row, -0.1 * md, 0.15 * md)
  if (!mb || !db) return null
  const groove = row.filter(([k]) => k > mb[0] && k < db[0]).map(([, v]) => v)
    .reduce<Vec3 | null>((m, v) => (!m || v[1] < m[1] ? v : m), null)
  return groove && mb[1] - groove[1] > 0.1 && db[1] - groove[1] > 0.1 ? groove : null
}

/** Точки замера: резцы 11/41 — вершины коронок плоским массивом xyz, первые
 *  моляры — центры мест (`place.position`) и ориентиры класса (`molarMark`,
 *  переведённые той же матрицей; null — нет). В мире — для `biteOf`, в
 *  системах групп челюстей — для `biteAt`. */
export interface BitePoints {
  u11: ArrayLike<number>
  l41: ArrayLike<number>
  c16: Vec3
  c26: Vec3
  c36: Vec3
  c46: Vec3
  k16?: Vec3 | null
  k26?: Vec3 | null
  k36?: Vec3 | null
  k46?: Vec3 | null
}

export function biteOf(w: BitePoints, band = EDGE_BAND): Bite {
  const u = incisal(w.u11, true, band)
  const l = incisal(w.l41, false, band)
  const marks = !!(w.k16 && w.k26 && w.k36 && w.k46)
  const rel = (k: Vec3 | null | undefined, g: Vec3 | null | undefined, cu: Vec3, cl: Vec3): number =>
    marks && k && g ? k[2] - g[2] : cu[2] - cl[2] + REL_I
  return {
    oj: u.frontZ - l.frontZ,
    ob: l.edgeY - u.edgeY,
    relR: rel(w.k16, w.k46, w.c16, w.c46),
    relL: rel(w.k26, w.k36, w.c26, w.c36),
    byMarks: marks,
  }
}

/** Прикус при любой позе по точкам в системах групп челюстей: сцена отдаёт
 *  точки один раз, `base`/`geo` и шаги секущей считаются без кадра. Сдвиги
 *  групп по y: верхняя `upperY`, нижняя `lowerY` (смыкание и уход из кадра). */
export function biteAt(p: BitePoints, pose: JawPose, upperY: number, lowerY: number): { bite: Bite; geo: OcclGeo } {
  const up = (q: Vec3): Vec3 => [q[0], q[1] + upperY, q[2]]
  const lo = (q: Vec3): Vec3 => poseLower(q, pose, lowerY)
  const opt = (q: Vec3 | null | undefined, f: (q: Vec3) => Vec3): Vec3 | null => (q ? f(q) : null)
  const map = (a: ArrayLike<number>, f: (q: Vec3) => Vec3): number[] => {
    const out: number[] = []
    for (let i = 0; i + 2 < a.length; i += 3) out.push(...f([a[i] as number, a[i + 1] as number, a[i + 2] as number]))
    return out
  }
  const l41 = map(p.l41, lo)
  const c36 = lo(p.c36)
  const c46 = lo(p.c46)
  const w: BitePoints = {
    u11: map(p.u11, up), l41, c16: up(p.c16), c26: up(p.c26), c36, c46,
    k16: opt(p.k16, up), k26: opt(p.k26, up), k36: opt(p.k36, lo), k46: opt(p.k46, lo),
  }
  const bite = biteOf(w)
  // точки, которыми меряется класс, — их и ставит поворот вокруг вертикали
  const m46 = (bite.byMarks && w.k46) || c46
  const m36 = (bite.byMarks && w.k36) || c36
  return {
    bite,
    geo: { z41: incisal(l41, false).frontZ, z46: (m46[2] + m36[2]) / 2, half: (Math.abs(m46[0]) + Math.abs(m36[0])) / 2 },
  }
}
