import type { Look } from './look'

/* Какая сцена играется при смене состояния зуба (B7, ступень 6) — чистый
   выбор по двум видам, чтобы сцена (`scene.ts`, WebGL) была лишь исполнением.
   Сцены — из макета: имплант вкручивается сверху и коронка садится на него;
   удалённый зуб выходит из лунки и растворяется; отсутствующий тает целиком,
   остаётся пунктир шейки; коронка (и тело моста) садится или «вдыхает»; живой зуб
   возвращается из лунки, из-под импланта или из призрака. Ничего не движется
   само — только вслед за действием человека, и при reduced-motion твины
   мгновенны (это решает `tween.ts`). */

export type Scene = 'implant' | 'extract' | 'ghost' | 'gold' | 'alive'

export function sceneFor(next: Look): Scene {
  if (next.implant) return 'implant'
  if (next.gone) return 'extract'
  if (next.ghost) return 'ghost'
  if (next.gold) return 'gold'
  return 'alive'
}

/** Откуда возвращается коронка: из лунки, из-под импланта, из призрака или
 *  ниоткуда (была на месте — тогда только перекраска или «вдох»). */
export type From = 'gone' | 'implant' | 'ghost' | null

export function comesFrom(prev: Look): From {
  if (prev.gone) return 'gone'
  if (prev.implant) return 'implant'
  if (prev.ghost) return 'ghost'
  return null
}

/** Длительности сцен, мс — те же, что в макете. */
export const MS = {
  screwIn: 900, crownSeat: 520, crownSeatDelay: 820, extract: 720, ghost: 500,
  screwOut: 600, socketFade: 300, crownReturn: 480, breath: 440, roots: 320, colour: 380,
} as const

/** Откуда поднимается коронка при возврате, мм по оси зуба: на пустое место — проявляется на месте. */
export const startLift = (from: From): number => (from === 'ghost' ? 0 : -4)
