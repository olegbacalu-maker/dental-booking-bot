import type { ToothInfo } from '../chart'
import { SURF, type Letter } from './toothGeometry'

/* Вид зуба по данным (B7, ступень 3): что видно и какого цвета каждая
   поверхность — чистая функция от модели сервера. Цвета состояний — из
   палитры сервера (`model.palette` = `teeth_svg.COLORS`), поэтому 2D, легенда
   и 3D красят одним цветом; свои здесь только материалы (эмаль, керамика,
   дентин, золото, десна, лунка, титан), их отделка по смыслу (`FINISH`, вид
   «Simplu» с 24.10) и свечение выбора. Ничего клинического
   не считается: «эффективное состояние» — тот же вывод, что у рисунка сервера
   (поверхность с кариесом окрашивает целый зуб, если сам зуб «здоров»), и он
   нужен только для покраски. */

export const COLOR = {
  enamel: 0xe9e1d1,
  ceramic: 0xf4f0e8,
  dentin: 0xd6c2a4,
  gold: 0xf2a93b,
  gum: 0xecb3ae,
  socket: 0x8b949e,
  /** винт сквозь десну (полупрозрачный, со свечением) */
  titan: 0xb9bec6,
  /** сам винт — чистый металл (metalness 1): цвет даёт отражение, основа темнее */
  screw: 0xaab0b8,
  /** тёплый бархат (sheen) эмали и дентина корня */
  sheenEnamel: 0xfff3e2,
  sheenDentin: 0xf5e6cc,
  glow: 0x0b6b7a,
  ringMark: 0x16a34a,
  ringDevital: 0xbe185d,
  ringImplant: 0x8b5cf6,
  ringSelected: 0x0f7b8a,
} as const

/** `#RRGGBB` → число; всё прочее — 0 (чёрный виден, тихий провал — нет). */
export function hex(s: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(s.trim())
  return m ? parseInt(m[1] ?? '0', 16) : 0
}

/** Смешение цветов по компонентам, как `Color.lerp`. */
export function lerpHex(a: number, b: number, k: number): number {
  const t = Math.min(1, Math.max(0, k))
  const ch = (shift: number): number => {
    const x = (a >> shift) & 0xff
    const y = (b >> shift) & 0xff
    return Math.round(x + (y - x) * t) & 0xff
  }
  return (ch(16) << 16) | (ch(8) << 8) | ch(0)
}

/** Отделка поверхности (вид «Simplu», прототип 19.10 `proto/odonto-look`, слово
 *  Олега «да уже лучше»; в продукте с 24.10): шероховатость, металл, лак,
 *  бархат, показатель преломления, сила блика. ЦВЕТА здесь нет — его даёт
 *  палитра сервера, отделка меняет только то, как поверхность ловит свет.
 *  Поля — те же имена, что у `MeshPhysicalMaterial`. */
export interface Finish {
  roughness: number
  metalness: number
  clearcoat: number
  clearcoatRoughness: number
  sheen: number
  ior: number
  specularIntensity: number
}

export const FINISH = {
  /** эмаль: лак и бархат, ior эмали 1,62 */
  enamel: { roughness: 0.4, metalness: 0, clearcoat: 0.7, clearcoatRoughness: 0.12, sheen: 0.35, ior: 1.62, specularIntensity: 0.7 },
  /** пломба — полированный композит, глаже эмали */
  fill: { roughness: 0.2, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.05, sheen: 0, ior: 1.55, specularIntensity: 0.9 },
  /** кариес — мел: матовый, почти без лака */
  caries: { roughness: 0.78, metalness: 0, clearcoat: 0.05, clearcoatRoughness: 0.6, sheen: 0.15, ior: 1.5, specularIntensity: 0.35 },
  /** коронка и тело моста — металлокерамика с глазурью: металл под лаком */
  crown: { roughness: 0.24, metalness: 0.55, clearcoat: 1, clearcoatRoughness: 0.04, sheen: 0, ior: 1.6, specularIntensity: 1 },
  /** коронка импланта — цирконий: плотный, белый, ior 2,15 */
  zirconia: { roughness: 0.16, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.03, sheen: 0.1, ior: 2.15, specularIntensity: 1 },
  /** корень — дентин с лёгким бархатом, без лака */
  dentin: { roughness: 0.58, metalness: 0, clearcoat: 0, clearcoatRoughness: 0, sheen: 0.3, ior: 1.5, specularIntensity: 1 },
  /** винт импланта — титан, чистый металл: отражает карту окружения */
  titanium: { roughness: 0.26, metalness: 1, clearcoat: 0.3, clearcoatRoughness: 0.2, sheen: 0, ior: 1.5, specularIntensity: 1 },
} as const satisfies Record<string, Finish>

const FIN_KEYS = ['roughness', 'metalness', 'clearcoat', 'clearcoatRoughness', 'sheen', 'ior', 'specularIntensity'] as const

/** Отделка поверхности коронки по смыслу: коронка и имплант — целиком, у живого
 *  зуба — по состоянию ЭТОЙ поверхности (`surface`: carie / obturatie / нет). */
export function finishFor(gold: boolean, implant: boolean, surface: string | undefined): Finish {
  if (gold) return FINISH.crown
  if (implant) return FINISH.zirconia
  if (surface === 'obturatie') return FINISH.fill
  if (surface === 'carie') return FINISH.caries
  return FINISH.enamel
}

/** Отделка между двумя — твин смены состояния по полям, как цвет. Конец твина —
 *  ровно `b`: `a + (b − a)·1` даёт хвост в последнем знаке (кариес → коронка:
 *  0,040000000000000036), и следующий `sameFinish` завёл бы лишний твин. */
export function mixFinish(a: Finish, b: Finish, k: number): Finish {
  const t = Math.min(1, Math.max(0, k))
  if (t === 1) return { ...b }
  const out: Finish = { ...a }
  for (const f of FIN_KEYS) out[f] = a[f] + (b[f] - a[f]) * t
  return out
}

export const sameFinish = (a: Finish, b: Finish): boolean => FIN_KEYS.every((f) => a[f] === b[f])

/** Нынешняя отделка материала — копией (материал сам — `Finish` по полям). */
export function finishOf(m: Finish): Finish {
  const out: Finish = { ...FINISH.enamel }
  for (const f of FIN_KEYS) out[f] = m[f]
  return out
}

/** Поставить отделку материалу: только эти семь полей, цвет и прозрачность не трогаются. */
export function setFinish(m: Finish, f: Finish): void {
  for (const k of FIN_KEYS) m[k] = f[k]
}

type Info = Pick<ToothInfo, 'state' | 'sfst' | 'mk' | 'bridge'>

/** Состояние, которым зуб окрашен целиком: поверхностная находка у «здорового»
 *  зуба красит его в кариес/пломбу — как у рисунка сервера. */
export function effState(t: Info): string {
  const v = Object.values(t.sfst ?? {})
  if (v.length && (t.state === 'ok' || t.state === 'carie' || t.state === 'obturatie')) {
    return v.includes('carie') ? 'carie' : 'obturatie'
  }
  return t.state
}

/** Состояния поверхностей, которые есть смысл красить (у коронки/импланта их нет). */
export function surfaceStates(t: Info): Record<string, string> {
  const st = effState(t)
  return st === 'carie' || st === 'obturatie' ? (t.sfst ?? {}) : {}
}

export interface Look {
  st: string
  pontic: boolean
  gone: boolean
  ghost: boolean
  gold: boolean
  implant: boolean
  mark: boolean
  /** «nerv extras»: кольцо у шейки ниже кольца «в работе» и подкрашенные корни */
  devital: boolean
  /** цвет каждой поверхности в порядке `SURF` */
  cols: number[]
  /** отделка каждой поверхности в порядке `SURF` (блеск по смыслу, не цвет) */
  fin: Finish[]
  opacity: number
  /** что видно */
  crown: boolean
  roots: boolean
  screw: boolean
  socket: boolean
  /** пустое место отсутствующего зуба: пунктирный контур шейки, как в 2D */
  gap: boolean
}

export function targetLook(t: Info, palette: Record<string, string>): Look {
  const st = effState(t)
  const pontic = t.bridge?.role === 'corp'
  const gone = st === 'extras'
  const ghost = st === 'lipsa' && !pontic
  const gold = st === 'coroana' || pontic
  const implant = st === 'implant'
  const sf = surfaceStates(t)
  const whole = (st === 'carie' || st === 'obturatie') && Object.keys(sf).length === 0
  const base = gold ? COLOR.gold : implant ? COLOR.ceramic : COLOR.enamel
  const cols = SURF.map((L: Letter) => {
    if (gold || implant) return base
    const sfs = sf[L]
    if (sfs) return lerpHex(base, hex(palette[sfs] ?? ''), 0.6)
    if (whole) return lerpHex(base, hex(palette[st] ?? ''), 0.32)
    return base
  })
  // отделка — по тому же правилу, что цвет: своя у поверхности с находкой, у зуба целиком — на всех пяти
  const fin = SURF.map((L: Letter) => finishFor(gold, implant, sf[L] ?? (whole ? st : undefined)))
  return {
    st, pontic, gone, ghost, gold, implant,
    mark: (t.mk ?? []).includes('tratament'),
    devital: (t.mk ?? []).includes('devital'),
    cols,
    fin,
    opacity: 1,
    // ⭐ отсутствующий зуб НЕ рисуется (26.09, Олег: «удаление не убирает зуб»):
    // призрак 0,22 на белом фоне читался сплошным белым зубом без корней
    crown: !gone && !ghost,
    roots: !gone && !implant && !ghost && !pontic,
    screw: implant,
    socket: gone,
    gap: ghost,
  }
}

/** Смена состояния, которая заслуживает сцены (ступень 6), а не плавной покраски. */
export function structChanged(prev: Look | null, next: Look): boolean {
  return prev !== null && (prev.st !== next.st || prev.pontic !== next.pontic)
}

/** Тот же вид до последнего поля (24.10). `paint` не трогает зуб, чей вид не
 *  изменился: после записи сцену смены состояния обрезал второй `paint` того же
 *  коммита (`setDim` с новым набором, `setPerio`) — его `applyLook` ставил
 *  видимость и положение итогового вида с первого кадра сцены (удаление и
 *  «lipsă» исчезали сразу, твин шёл на невидимой коронке). Сравнение ПОЛНОЕ, по
 *  всем ключам вида: новое поле `Look` попадает в него само — иначе настоящая
 *  смена (гашение, призрак, пародонт) молча не применилась бы. */
export function sameLook(a: Look | null, b: Look): boolean {
  return a !== null && same(a, b)
}

function same(x: unknown, y: unknown): boolean {
  if (x === y) return true
  if (Array.isArray(x) && Array.isArray(y)) return x.length === y.length && x.every((v, i) => same(v, y[i]))
  if (x !== null && y !== null && typeof x === 'object' && typeof y === 'object') {
    const a = x as Record<string, unknown>
    const b = y as Record<string, unknown>
    const ka = Object.keys(a)
    return ka.length === Object.keys(b).length && ka.every((k) => k in b && same(a[k], b[k]))
  }
  return false
}

/** Прозрачность материала (24.10, находка `odo-modes` и `odo-look`). В three r151+
 *  `transparent` — параметр ПРОГРАММЫ шейдера (`#define OPAQUE`: альфа
 *  принудительно 1), а смену three сам не замечает (`needsProgramChange` её не
 *  сверяет): без `needsUpdate` погашенная легендой коронка оставалась
 *  непрозрачной, а сцены смены состояния «хлопали» вместо плавного гашения.
 *  Десна в «Rădăcini» работала случайно — двусторонним прозрачным three ставит
 *  `needsUpdate` сам. Пересборка — только при НАСТОЯЩЕЙ смене: на каждом `paint`
 *  она меняла бы программу впустую. */
export function setTransparent(m: { transparent: boolean; needsUpdate: boolean }, on: boolean): void {
  if (m.transparent === on) return
  m.transparent = on
  m.needsUpdate = true
}
