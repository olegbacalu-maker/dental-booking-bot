import { gumWarpFrame, vertexNormals, warpGum, type WarpTooth } from './gum'
import { placeOf, type Shapes, type TeethPlan } from './occlusionPlan'

/* Десна прикуса (координатор 08.11): конечная форма десны при плане зубов — вне главного
   потока. На месте первая деформация десны стоила 50–60 мс одним кадром (`warpGum` и
   нормали по 41 тыс. треугольников, холодный JIT), на медленном ПК клиники — больше.
   Здесь — по одной форме на план; кадры твина только смешивают «было» и «стало»
   (`scene.warpGums`), ~1 мс. Чистые числа, three нет — едет и в воркер. */

/** Зуб челюсти для рамки: номер, станция дуги, шейка и место в плоскости дуги. */
export interface FrameTooth { n: number; u: number; neckY: number; x: number; z: number }
/** Сетка десны, как построена (места раскладки), и её рамка (`gumWarpFrame`). */
export interface GumIn { positions: Float32Array; index: Uint32Array; A: number; D: number; apex: number; teeth: FrameTooth[]; occ: number }
export interface GumStore { base: Float32Array; index: Uint32Array; u: Float32Array; depth: Float32Array; tu: ReadonlyMap<number, number> }
export interface GumShape { pos: Float32Array; nor: Float32Array }

export function gumStore(g: GumIn): GumStore {
  const fr = gumWarpFrame(g.positions, g.A, g.D, g.apex, g.teeth, g.occ)
  return { base: g.positions, index: g.index, u: fr.u, depth: fr.depth, tu: new Map(g.teeth.map((t) => [t.n, t.u])) }
}

/** Конечная форма десны при плане зубов: вершины вслед за местами `placeOf` (k = 1) и
 *  нормали, как у three. Зубы челюсти — те, что в рамке (и скрытые: двигаются и они). */
export function gumTarget(G: GumStore, S: Shapes, t: TeethPlan): GumShape {
  const wt: WarpTooth[] = []
  for (const [n, u] of G.tu) {
    const sh = S.get(n)
    if (sh) wt.push({ u, from: sh.place, to: placeOf(n, sh.place, t, 1) })
  }
  wt.sort((a, b) => a.u - b.u)
  const pos = warpGum(G.base, G.u, G.depth, wt)
  return { pos, nor: vertexNormals(pos, G.index) }
}
