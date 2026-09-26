import type { ToothInfo } from '../chart'
import { SURF, type Letter } from './toothGeometry'

/* Вид зуба по данным (B7, ступень 3): что видно и какого цвета каждая
   поверхность — чистая функция от модели сервера. Цвета состояний — из
   палитры сервера (`model.palette` = `teeth_svg.COLORS`), поэтому 2D, легенда
   и 3D красят одним цветом; свои здесь только материалы (эмаль, керамика,
   дентин, золото, десна, лунка, титан) и свечение выбора. Ничего клинического
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
  titan: 0xb9bec6,
  glow: 0x0b6b7a,
  ringMark: 0x16a34a,
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
  /** цвет каждой поверхности в порядке `SURF` */
  cols: number[]
  opacity: number
  metalness: number
  roughness: number
  /** что видно */
  crown: boolean
  roots: boolean
  screw: boolean
  socket: boolean
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
  return {
    st, pontic, gone, ghost, gold, implant,
    mark: (t.mk ?? []).includes('tratament'),
    cols,
    opacity: ghost ? 0.22 : 1,
    metalness: gold ? 0.85 : 0,
    roughness: gold ? 0.28 : implant ? 0.22 : 0.32,
    crown: !gone,
    roots: !gone && !implant && !ghost && !pontic,
    screw: implant,
    socket: gone,
  }
}

/** Смена состояния, которая заслуживает сцены (ступень 6), а не плавной покраски. */
export function structChanged(prev: Look | null, next: Look): boolean {
  return prev !== null && (prev.st !== next.st || prev.pontic !== next.pontic)
}
