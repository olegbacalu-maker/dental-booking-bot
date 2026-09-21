import { DONUT_C, DONUT_R, donutArcs, gaugeArc, linePlot } from '../../utils/chart'

/* Три фигуры аналитики. Разметка и классы — те же, что у серверных
   `core/charts.py` (panel.css: `.linechart`, `.donut`, `.gauge`), поэтому
   картинка та же картинка, включая анимацию появления: её делает CSS. */

const T = {
  empty: '— nicio programare în perioadă —',
  none: '— încă fără date —',
  byDays: 'Programări pe zile',
} as const

export function LineDays({ labels, values, tone }:
{ labels: string[]; values: number[]; tone: string }) {
  if (!values.length) return <p className="hint">{T.empty}</p>
  const p = linePlot(labels, values)
  return (
    <svg className="linechart" viewBox={`0 0 ${p.w} ${p.h}`} width="100%"
      role="img" aria-label={T.byDays}>
      <g className="lc-grid">
        {p.grid.map((g) => (
          <line key={g.label} x1={p.x0} y1={g.y} x2={p.w - 8} y2={g.y} />
        ))}
      </g>
      <g className="lc-ax">
        {p.grid.map((g) => (
          <text key={g.label} x={p.x0 - 8} y={g.y + 4} textAnchor="end">{g.label}</text>
        ))}
        {p.xLabels.map((x) => (
          <text key={x.text} x={x.x} y={p.h - 7} textAnchor="middle">{x.text}</text>
        ))}
      </g>
      <polygon className="lc-a" points={`${p.x0},${p.yZero} ${p.points} ${p.x1},${p.yZero}`}
        style={{ fill: tone }} />
      <polyline className="lc-l" points={p.points} style={{ stroke: tone }} />
      <g className="lc-d" style={{ fill: tone }}>
        {p.dots.map((d, i) => <circle key={i} cx={d.x} cy={d.y} r={4} />)}
      </g>
      {p.dots.map((d, i) => (
        <text key={i} className="ld-v" x={d.x} y={d.y - 11} textAnchor="middle">{d.v}</text>
      ))}
    </svg>
  )
}

export function Donut({ parts, label }:
{ parts: { label: string; value: number; color: string }[]; label: string }) {
  const { total, arcs } = donutArcs(parts)
  if (!total) return <p className="hint">{T.none}</p>
  return (
    <svg className="donut" viewBox="0 0 140 140" width="140" height="140"
      role="img" aria-label={label}>
      {arcs.map((a) => (
        <circle key={a.label} cx={DONUT_C} cy={DONUT_C} r={DONUT_R} fill="none"
          stroke={a.color} strokeWidth="20" strokeDasharray={a.dash}
          strokeDashoffset={a.offset} transform={`rotate(-90 ${DONUT_C} ${DONUT_C})`} />
      ))}
      <text className="dn-v" x={DONUT_C} y={DONUT_C - 2} textAnchor="middle">{total}</text>
      <text className="dn-l" x={DONUT_C} y={DONUT_C + 16} textAnchor="middle">{label}</text>
    </svg>
  )
}

export function Gauge({ pct, tone, label }: { pct: number; tone: string; label: string }) {
  const g = gaugeArc(pct)
  return (
    <svg className="gauge" viewBox="0 0 150 96" width="100%" height="96"
      role="img" aria-label={`${label} ${g.pct}%`}>
      <path className="gg-bg" d={g.path} />
      <path className="gg-v" d={g.path} style={{ stroke: tone }} strokeDasharray={g.dash} />
      <text className="gg-t" x={75} y={68} textAnchor="middle">{g.pct}%</text>
    </svg>
  )
}
