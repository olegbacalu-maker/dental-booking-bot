import type { PlacedTooth, Vec3 } from './arch'

/* Камера у зуба (01.10, «focus»): чистые числа для сцены — куда смотреть и
   откуда. Цель — середина коронки, азимут — щёчная нормаль зуба (смотрим
   снаружи дуги, как врач на пациента), чуть снизу у верхних и чуть сверху у
   нижних, чтобы жевательная поверхность не ушла в ребро. Радиус — ближе
   минимума колеса не опускается, иначе первый же тик колеса дёргал бы камеру
   назад. Ничего клинического здесь нет — только где стоит камера. */

/** Расстояние камеры до зуба, мм; минимум колеса/щипка в сцене — 70. */
export const FOCUS_R = 72

export interface FocusOrbit {
  target: Vec3
  theta: number
  phi: number
  r: number
}

const rad = (d: number): number => (d * Math.PI) / 180

/**
 * @param p      зуб на дуге (позиция и базис, `layoutArch`)
 * @param crown  высота коронки, мм (размеры с сервера)
 * @param jawY   смещение группы челюсти по y в момент фокуса (смыкание, уход из кадра)
 * @param upper  верхняя челюсть
 */
export function focusOrbit(p: PlacedTooth, crown: number, jawY: number, upper: boolean): FocusOrbit {
  const h = crown / 2
  const target: Vec3 = [
    p.position[0] + p.yAxis[0] * h,
    p.position[1] + p.yAxis[1] * h + jawY,
    p.position[2] + p.yAxis[2] * h,
  ]
  return {
    target,
    theta: Math.atan2(p.zAxis[0], p.zAxis[2]),
    phi: rad(upper ? 95 : 72),
    r: FOCUS_R,
  }
}

/**
 * Камера у зуба для листа пародонтограммы (06.10): сверху на жевательную
 * поверхность со щёчной стороны — видны ВСЕ шесть точек края сразу, щёчные и
 * язычные. Иначе курсор, идущий по точкам листа (три щёчные, три язычные),
 * гонял бы камеру вокруг зуба каждые три цифры. Ниже минимума колеса —
 * намеренно: смотрим на один зуб, а не на дугу.
 */
export function focusOcclusal(p: PlacedTooth, crown: number, jawY: number, upper: boolean): FocusOrbit {
  const f = focusOrbit(p, crown, jawY, upper)
  return { ...f, phi: rad(upper ? 138 : 42), r: 58 }
}

/** Ближайший поворот от `from` к азимуту `to`: орбита после перетаскивания
 *  может стоять на 7 рад, и прямое равенство цели гнало бы камеру кругом. */
export function nearestTheta(from: number, to: number): number {
  const TAU = Math.PI * 2
  let d = (to - from) % TAU
  if (d > Math.PI) d -= TAU
  if (d <= -Math.PI) d += TAU
  return from + d
}
