import type { PlacedTooth, Vec3 } from './arch'
import type { Cls } from './toothGeometry'

/* Постановка зуба (06.10, кадры до/после — слово Олега «нравится»): зуб стоит
   не столбиком, а как в челюсти. Три поправки к месту из `layoutArch`:
   - tip — коронка наклонена к мезиальной стороне (угол по Andrews, смягчён);
   - torque — наклон в щёчно-язычной плоскости: верхние резцы вперёд, нижние
     моляры к языку (кривая Уилсона);
   - шейка сдвинута к корню так, чтобы вершины коронок легли в одну
     окклюзионную плоскость (у верхних боковых резцов — на 0,7 мм короче, у
     нижних премоляров — кривая Шпее). Отсюда сама собой волна десны:
     у клыков и центральных шейка выше, к молярам ниже — как у живого рта.
   Поворот — вокруг середины шейки, поэтому сетка зуба и всё, что висит на
   группе (кольца, номер, винт), едут вместе. Мезиальная сторона у сетки
   всегда −x, и отражённые квадранты 2 и 4 наклоняются правильно сами. */

interface PoseSpec { tip: number; torque: number; extra: number }

const UPPER: Record<Cls, PoseSpec> = {
  incisor_c: { tip: 2, torque: 7, extra: -0.2 },
  incisor_l: { tip: 3, torque: 6, extra: 0.7 },
  canine: { tip: 4, torque: 3, extra: 0 },
  premolar: { tip: 1, torque: -4, extra: 0.1 },
  molar: { tip: 2, torque: -7, extra: 0 },
}
const LOWER: Record<Cls, PoseSpec> = {
  incisor_c: { tip: 1, torque: 4, extra: 0 },
  incisor_l: { tip: 1, torque: 4, extra: 0 },
  canine: { tip: 3, torque: -3, extra: 0.2 },
  premolar: { tip: 1, torque: -7, extra: 0.7 },
  molar: { tip: 1, torque: -12, extra: 0 },
}

const rad = (d: number): number => (d * Math.PI) / 180

/** Добавочный torque поставленного зуба, градусы (+ — коронка к щеке/губе): тот
 *  же поворот, что `posed` делает углом torque, — вокруг мезио-дистальной оси зуба
 *  через середину шейки, поэтому `torqued(posed(p, …torque b), Δ)` = место с
 *  torque b + Δ (держит `pose.test`). Квадранты 2 и 4 зеркальные (базис с
 *  отрицательным определителем): поворот «в базисе зуба» в мире идёт в другую
 *  сторону. Прикус по подтипу II/1 и II/2 (этап 4 «ocluzie») — через это. */
export function torqued(p: PlacedTooth, deg: number): PlacedTooth {
  if (!deg) return p
  const a = (p.mirror ? -1 : 1) * rad(deg)
  const k = p.xAxis
  const c = Math.cos(a)
  const s = Math.sin(a)
  const rot = (v: Vec3): Vec3 => {
    const d = k[0] * v[0] + k[1] * v[1] + k[2] * v[2]
    const cr: Vec3 = [k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0]]
    return [v[0] * c + cr[0] * s + k[0] * d * (1 - c), v[1] * c + cr[1] * s + k[1] * d * (1 - c), v[2] * c + cr[2] * s + k[2] * d * (1 - c)]
  }
  return { ...p, yAxis: rot(p.yAxis), zAxis: rot(p.zAxis) }
}

/** Место зуба с наклоном и сдвигом шейки. `tip` — вершина этой коронки над
 *  шейкой, `tipRef` — у первого моляра той же челюсти (он остаётся на месте). */
export function posed(p: PlacedTooth, cls: Cls, upper: boolean, tip: number, tipRef: number): PlacedTooth {
  const spec = (upper ? UPPER : LOWER)[cls]
  const a = rad(spec.tip)
  const b = rad(spec.torque)
  const ex: Vec3 = [Math.cos(a), Math.sin(a), 0]
  const ey: Vec3 = [-Math.sin(a) * Math.cos(b), Math.cos(a) * Math.cos(b), Math.sin(b)]
  const ez: Vec3 = [Math.sin(a) * Math.sin(b), -Math.cos(a) * Math.sin(b), Math.cos(b)]
  const B = (v: Vec3): Vec3 => [
    p.xAxis[0] * v[0] + p.yAxis[0] * v[1] + p.zAxis[0] * v[2],
    p.xAxis[1] * v[0] + p.yAxis[1] * v[1] + p.zAxis[1] * v[2],
    p.xAxis[2] * v[0] + p.yAxis[2] * v[1] + p.zAxis[2] * v[2],
  ]
  // к корню — против окклюзионной оси; выше эталона зуб поднимается не больше
  // чем на 2,5 мм: своя модель моляра на ~2 мм ниже формулы, по которой стоит
  // плоскость (07.10), а коронка-обломок не должна подлетать к плоскости
  const shift = Math.max(-2.5, tip - tipRef + spec.extra)
  const position: Vec3 = [
    p.position[0] - p.yAxis[0] * shift,
    p.position[1] - p.yAxis[1] * shift,
    p.position[2] - p.yAxis[2] * shift,
  ]
  return { ...p, position, xAxis: B(ex), yAxis: B(ey), zAxis: B(ez) }
}
