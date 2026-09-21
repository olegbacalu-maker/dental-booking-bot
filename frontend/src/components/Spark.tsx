import { sparkPoints } from '../utils/chart'

/** Ряд за две недели инлайновым SVG — без библиотек: программа ставится одним
 *  exe и работает без интернета. */
export function Spark({ series, tone }: { series: number[]; tone: string }) {
  const pts = sparkPoints(series)
  if (!pts) return null
  return (
    <svg className="spark" viewBox="0 0 100 26" width="100%" height="26"
      preserveAspectRatio="none" aria-hidden="true">
      <polygon className="sp-a" points={`0,26 ${pts} 100,26`} style={{ fill: tone }} />
      {/* ⛔ `vector-effect`: без него `preserveAspectRatio="none"` размазал бы
          штрих вместе с координатами. */}
      <polyline className="sp-l" points={pts} vectorEffect="non-scaling-stroke"
        style={{ stroke: tone }} />
    </svg>
  )
}
