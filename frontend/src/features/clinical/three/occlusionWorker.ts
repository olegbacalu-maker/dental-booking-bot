import { gumWarpFrame } from './gum'
import { occlusionPlan, type ToothShape } from './occlusionPlan'
import type { AskFrame, AskPlan, Reply, ShapeMsg } from './occlusionAsync'

/* Прикус в 3D: расчёт плана и рамки десны ВНЕ главного потока (координатор 08.11:
   ни одного куска > 50 мс от плана при открытии вкладки и «Ocluzie»). Чистые числа
   (`occlusionPlan`, `gum.gumWarpFrame`), three здесь нет; формулы — те же модули, что
   у сцены, поэтому план из воркера равен плану на месте (`occlusionAsync.test`).
   Едет внутри бандла (`?worker&inline`): отдельный файл не прошёл бы маршрут статики. */

// типы проекта — DOM; у воркера свой `self` (lib webworker рядом с DOM даёт двойные имена)
const ctx = self as unknown as {
  onmessage: ((ev: MessageEvent<ShapeMsg | AskPlan | AskFrame>) => void) | null
  postMessage(m: Reply, transfer?: Transferable[]): void
}
const shapes = new Map<string, Map<number, ToothShape>>()

ctx.onmessage = (ev) => {
  const m = ev.data
  if (m.t === 'shapes') {
    if (shapes.size > 2) shapes.clear()
    shapes.set(m.fp, new Map(m.shapes))
    return
  }
  if (m.t === 'plan') {
    const S = shapes.get(m.fp)
    const plan = S ? occlusionPlan(m.rec, S, m.closeY, new Set(m.shown)) : null
    ctx.postMessage({ t: 'plan', id: m.id, plan, missing: !S })
    return
  }
  const fr = gumWarpFrame(m.positions, m.A, m.D, m.apex, m.teeth, m.occ)
  ctx.postMessage({ t: 'frame', id: m.id, u: fr.u, depth: fr.depth }, [fr.u.buffer, fr.depth.buffer])
}
