import { useState } from 'react'
import { groupThousands } from '../../utils/fx'

/* Фигуры раздела «Statistici» (B8, 27.09). Как и остальные графики программы —
   без библиотек: SVG и числа, цвета из темы клиники.
   Приёмы взяты у открытых шаблонов shadcn/ui dashboard-01 (MIT) и Tremor
   Dashboard OSS (Apache-2.0), код не копировался: столбцы с подсказкой вместо
   подписи у каждой точки, полоса долей вместо кольца. */

/** «Круглый» шаг оси: 1, 2, 2.5, 5 × 10^k — подписи оси человеко-читаемы. */
export function niceStep(raw: number): number {
  if (raw <= 1) return 1
  const p = 10 ** Math.floor(Math.log10(raw))
  const m = raw / p
  const k = m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10
  return k * p
}

interface ColumnsProps {
  labels: string[]
  hints: string[]
  values: number[]
  /** Текст значения в подсказке — деньги форматирует сервер. */
  texts?: string[] | undefined
  unit: string
  tone: string
  ariaLabel: string
  /** Фраза для периода без единого значения. */
  empty: string
}

/**
 * Столбцы по дням или неделям. Подписи у каждого столбца нет — число
 * показывает подсказка при наведении и касании, а ось Y даёт масштаб.
 * ⚠️ Нулевой день (воскресенье, клиника закрыта) — пустое место, а не столбик
 * высотой в пиксель: «ничего не было» так и читается.
 */
export function Columns({ labels, hints, values, texts, unit, tone, ariaLabel, empty }: ColumnsProps) {
  const [hot, setHot] = useState<number | null>(null)
  /* Пустой период — фраза вместо пустой сетки 0…1: сетка без столбиков
     выглядела бы как недогруженный график. */
  if (!values.some((v) => v > 0)) return <p className="hint stx-empty">{empty}</p>
  const w = 720, h = 236, l = 56, r = 8, t = 10, b = 28
  const iw = w - l - r, ih = h - t - b
  /* Шаг — «круглый», засечек 1–5 по верху данных: потолок почти впритык к
     максимуму, без полупустой шкалы (24 записи → ось до 25, а не до 40). */
  const max = Math.max(...values, 1)
  const step = niceStep(max / 5)
  const ticks = Math.max(1, Math.ceil(max / step))
  const top = step * ticks
  const dx = iw / values.length
  const bw = Math.max(3, Math.min(30, dx * 0.62))
  const y = (v: number) => t + ih - ih * (v / top)
  const every = Math.max(1, Math.ceil(labels.length / 10))
  const text = (i: number) => (texts ? texts[i] : `${values[i]} ${unit}`)
  const tip = hot === null ? null : {
    left: Math.min(92, Math.max(8, ((l + dx * (hot + 0.5)) / w) * 100)),
    hint: hints[hot],
    text: text(hot),
  }
  return (
    <div className="stx-cols" onPointerLeave={() => setHot(null)}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={ariaLabel}>
        {Array.from({ length: ticks + 1 }, (_, k) => k).map((k) => (
          <g key={k}>
            <line className="stx-grid" x1={l} x2={w - r} y1={y(step * k)} y2={y(step * k)} />
            <text className="stx-ax" x={l - 8} y={y(step * k) + 4} textAnchor="end">
              {groupThousands(Math.round(step * k))}
            </text>
          </g>
        ))}
        {values.map((v, i) => {
          const x = l + dx * i + (dx - bw) / 2
          return (
            <g key={i}>
              {v > 0 && (
                <rect className={hot === i ? 'stx-bar on' : 'stx-bar'} x={x} y={y(v)}
                  width={bw} height={Math.max(1, y(0) - y(v))} rx={Math.min(4, bw / 3)}
                  style={{ fill: tone }} />
              )}
              <rect className="stx-hit" x={l + dx * i} y={t} width={dx} height={ih}
                onPointerEnter={() => setHot(i)} onPointerDown={() => setHot(i)}>
                <title>{`${hints[i]}: ${text(i)}`}</title>
              </rect>
            </g>
          )
        })}
        {labels.map((s, i) => (i % every === 0 || i === labels.length - 1) && (
          <text key={i} className="stx-ax" x={l + dx * (i + 0.5)} y={h - 8} textAnchor="middle">{s}</text>
        ))}
      </svg>
      {tip && (
        <div className="stx-tip" style={{ left: `${tip.left}%` }}>
          <span>{tip.hint}</span>
          <b>{tip.text}</b>
        </div>
      )}
    </div>
  )
}

interface Part {
  key: string
  label: string
  text: string
  color: string
  pct: number
}

/** Полоса долей (приём Tremor «CategoryBar»): одна строка вместо кольца. */
export function CategoryBar({ parts }: { parts: Part[] }) {
  const shown = parts.filter((p) => p.pct > 0)
  return (
    <div className="stx-cat">
      <div className="stx-cat-bar" aria-hidden="true">
        {shown.map((p) => (
          <span key={p.key} style={{ width: `${Math.max(p.pct, 2)}%`, background: p.color }} />
        ))}
      </div>
      <ul className="stx-cat-legend">
        {parts.map((p) => (
          <li key={p.key}>
            <i style={{ background: p.color }} />
            <span>{p.label} <em>{p.pct}%</em></span>
            <b>{p.text}</b>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Шкала доли 0–100: присутствие, загрузка. */
export function Meter({ pct, tone }: { pct: number; tone: string }) {
  return (
    <div className="stx-meter" aria-hidden="true">
      <span style={{ width: `${Math.min(Math.max(pct, 0), 100)}%`, background: tone }} />
    </div>
  )
}
