import { gumStore, gumTarget, type GumStore } from './occlusionGum'
import { occlusionPlan, type ToothShape } from './occlusionPlan'
import type { AskPlan, AskShape, GumMsg, Reply, ShapeMsg } from './occlusionAsync'

/* Прикус в 3D: план и конечная форма десны ВНЕ главного потока (координатор 08.11:
   ни одного куска > 50 мс от плана при открытии вкладки и «Ocluzie»). Чистые числа
   (`occlusionPlan`, `occlusionGum`), three здесь нет; формулы — те же модули, что
   у сцены, поэтому план из воркера равен плану на месте (`occlusionAsync.test`).
   Едет внутри бандла (`?worker&inline`): отдельный файл не прошёл бы маршрут статики. */

// типы проекта — DOM; у воркера свой `self` (lib webworker рядом с DOM даёт двойные имена)
const ctx = self as unknown as {
  onmessage: ((ev: MessageEvent<ShapeMsg | GumMsg | AskPlan | AskShape>) => void) | null
  postMessage(m: Reply, transfer?: Transferable[]): void
}
const shapes = new Map<string, Map<number, ToothShape>>()
const gums = new Map<number, GumStore>()

ctx.onmessage = (ev) => {
  const m = ev.data
  if (m.t === 'shapes') {
    if (shapes.size > 2) shapes.clear()
    shapes.set(m.fp, new Map(m.shapes))
    return
  }
  if (m.t === 'gum') {
    if (gums.size > 4) gums.delete(gums.keys().next().value as number)
    gums.set(m.gid, gumStore(m.gum))
    return
  }
  if (m.t === 'plan') {
    const S = shapes.get(m.fp)
    const plan = S ? occlusionPlan(m.rec, S, m.closeY, new Set(m.shown)) : null
    ctx.postMessage({ t: 'plan', id: m.id, plan, missing: !S })
    return
  }
  const S = shapes.get(m.fp)
  const G = gums.get(m.gid)
  if (!S || !G) {
    ctx.postMessage({ t: 'shape', id: m.id, shape: null, missing: true })
    return
  }
  const shape = gumTarget(G, S, m.teeth)
  ctx.postMessage({ t: 'shape', id: m.id, shape, missing: false }, [shape.pos.buffer, shape.nor.buffer])
}
