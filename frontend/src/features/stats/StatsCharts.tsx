import { groupThousands } from '../../utils/fx'

/* Фигуры раздела «Statistici» (B8, 27.09; вид по макету Олега 08.10). Как и
   остальные графики программы — без библиотек: разметка, числа и цвета темы.
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
  /** День недели над датой («Vi / 02.10») — только у дневных корзин. */
  wdays?: string[] | undefined
  values: number[]
  /** Текст значения в подсказке — деньги форматирует сервер. */
  texts?: string[] | undefined
  unit: string
  ariaLabel: string
  /** Фраза для периода без единого значения. */
  empty: string
}

/**
 * Столбцы по дням или неделям (макет 08.10): один цвет, скругление сверху,
 * ось Y на 3–4 деления, числом подписан только самый высокий столбец, у
 * каждого — подсказка при наведении и фокусе. Столбец фокусируем и назван
 * (`aria-label`): график читается и с клавиатуры.
 * ⚠️ Нулевой день (воскресенье, клиника закрыта) — пустое место, а не столбик
 * высотой в пиксель: «ничего не было» так и читается.
 */
export function Columns({ labels, hints, wdays, values, texts, unit, ariaLabel, empty }: ColumnsProps) {
  /* Пустой период — фраза вместо пустой сетки 0…1: сетка без столбиков
     выглядела бы как недогруженный график. */
  if (!values.some((v) => v > 0)) return <p className="hint stx-empty">{empty}</p>
  const max = Math.max(...values, 1)
  /* Шаг — «круглый», засечек 3–4 по верху данных: потолок — ближайшая
     засечка над максимумом, без полупустой шкалы. */
  const step = niceStep(max / 4)
  const ticks = Math.max(1, Math.ceil(max / step))
  const top = step * ticks
  const text = (i: number) => (texts ? texts[i] : `${values[i]} ${unit}`)
  const best = values.indexOf(max)
  const every = Math.max(1, Math.ceil(labels.length / 10))
  return (
    <div className="stx-cols" role="group" aria-label={ariaLabel}>
      <div className="stx-plot">
        {Array.from({ length: ticks + 1 }, (_, k) => (
          <div key={k} className="stx-tick" style={{ bottom: `${(100 * k) / ticks}%` }} aria-hidden="true">
            <span>{groupThousands(Math.round(step * k))}</span>
          </div>
        ))}
        <div className="stx-bars">
          {values.map((v, i) => (
            <div key={i} className="stx-bcol" tabIndex={0} aria-label={`${hints[i]}: ${text(i)}`}>
              <span className="stx-tip" aria-hidden="true"><span>{hints[i]}:</span> <b>{text(i)}</b></span>
              {i === best && <span className="stx-top" aria-hidden="true">{texts ? texts[i] : values[i]}</span>}
              {v > 0 && <div className="stx-bar" style={{ height: `${(100 * v) / top}%` }} />}
            </div>
          ))}
        </div>
      </div>
      <div className="stx-xax" aria-hidden="true">
        {labels.map((s, i) => (
          <div key={i}>
            {(i % every === 0 || i === labels.length - 1) ? (
              <>{wdays?.[i] ? <b>{wdays[i]}</b> : null}<span>{s}</span></>
            ) : null}
          </div>
        ))}
      </div>
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
            <span>{p.label} <em>· {p.pct}%</em></span>
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
