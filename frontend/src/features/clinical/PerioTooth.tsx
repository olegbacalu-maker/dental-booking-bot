import type { ChangeEvent } from 'react'
import { Tooth } from './Tooth'
import type { PerioEdit, PerioLimits, PerioModel, PerioTooth as ToothMeta } from './perio'
import type { Grade, Kind } from './usePerio'

/*
 * Колонка одного зуба: шесть точек глубины и шесть рецессии, номер между
 * ними, степени внизу, рисунок зуба со стороны средней линии.
 *
 * ⛔ Порядок строк закреплён и повторяет старую страницу: глубина
 * вестибулярно, рецессия вестибулярно, НОМЕР, рецессия орально, глубина
 * орально. Он же порядок диктовки вслух и порядок чисел в базе — в строке
 * «3,2,3,4,2,5» нет имён точек, только позиция, и перестановка молча
 * переписала бы чужие измерения.
 * ⚠️ Ноль показывается ПУСТЫМ полем: ноль в базе значит «не измеряли», а
 * написанный нолик врач прочитал бы измерением.
 * ⚠️ Точка кровоточивости — только у глубины. Второй набор точек у рецессии
 * молча удваивал бы BOP при сборке осмотра.
 */
interface Props {
  n: number
  row: PerioEdit
  meta: ToothMeta
  limits: PerioLimits
  sites: PerioModel['sites']
  grades: PerioModel['grades']
  /** Нижняя дуга: рисунок зуба идёт ПЕРЕД цифрами (к средней линии). */
  lower?: boolean
  onCell: (n: number, kind: Kind, i: number, raw: string, el: HTMLInputElement) => void
  onBop: (n: number, i: number) => void
  onGrade: (n: number, kind: Grade, value: number) => void
  /** Клик по рисунку зуба — фокус на первую точку этой колонки. */
  onPick: (n: number) => void
}

const WHAT: Record<Kind, string> = { pd: 'adâncime', rec: 'recesiune' }

export function PerioTooth({
  n, row, meta, limits, sites, grades, lower, onCell, onBop, onGrade, onPick,
}: Props) {
  const cell = (kind: Kind, i: number) => {
    const value = row[kind][i] ?? 0
    const site = sites[i]?.label ?? ''
    const deep = kind === 'pd' && value >= limits.deep
    const change = (e: ChangeEvent<HTMLInputElement>) =>
      onCell(n, kind, i, e.target.value, e.currentTarget)
    return (
      <div className={`pcell${deep ? ' deep' : ''}`} key={`${kind}${i}`}>
        <input
          type="text"
          inputMode="numeric"
          maxLength={2}
          value={value ? String(value) : ''}
          data-k={kind}
          data-i={i}
          data-n={n}
          title={`${WHAT[kind]} · ${site}`}
          aria-label={`${n} ${WHAT[kind]} ${site}`}
          onChange={change}
        />
        {kind === 'pd' && (
          <button
            type="button"
            className={`pdot${row.bop[i] === '1' ? ' on' : ''}`}
            data-i={i}
            aria-pressed={row.bop[i] === '1'}
            title={`Sângerare la sondare (${site})`}
            onClick={() => onBop(n, i)}
          />
        )}
      </div>
    )
  }

  const line = (kind: Kind, from: number) => (
    <div className={`prow${kind === 'rec' ? ' rec' : ''}`}>
      {[0, 1, 2].map((k) => cell(kind, from + k))}
    </div>
  )

  const pick = (kind: Grade) => {
    const top = kind === 'mob' ? limits.mob_max : limits.furc_max
    const labels = grades[kind]
    return (
      <select
        value={String(row[kind])}
        data-k={kind}
        title={kind === 'mob' ? 'Mobilitate (Miller)' : 'Furcație (Hamp)'}
        aria-label={`${n} ${kind === 'mob' ? 'mobilitate' : 'furcație'}`}
        onChange={(e) => onGrade(n, kind, Number(e.target.value))}
      >
        {Array.from({ length: top + 1 }, (_, i) => (
          <option key={i} value={String(i)}>{i ? (labels[String(i)] ?? i) : '—'}</option>
        ))}
      </select>
    )
  }

  const pic = (
    <div className="ptpic">
      <Tooth n={n} info={meta} view="frontal" {...(lower ? { lower: true } : {})} onSelect={onPick} />
    </div>
  )

  return (
    <div
      className={`ptooth${meta.absent ? ' absent' : ''}`}
      data-tooth={n}
      {...(meta.absent ? { title: 'Dinte marcat absent în odontogramă' } : {})}
    >
      {lower ? pic : null}
      {line('pd', 0)}
      {line('rec', 0)}
      <b className="pnum">{n}</b>
      {line('rec', 3)}
      {line('pd', 3)}
      <div className="pmf">{pick('mob')}{pick('furc')}</div>
      {lower ? null : pic}
    </div>
  )
}
