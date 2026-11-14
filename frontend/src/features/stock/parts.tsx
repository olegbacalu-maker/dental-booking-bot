import type { ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/icons'
import { dmy, num, orderState, packText, qtyText, type Item, type Kind, type Move } from './stock'

export function F({ label, hint, bad, children }: { label: string; hint?: ReactNode | undefined; bad?: string | undefined; children: ReactNode }) {
  return (
    <div className={`rg-f${bad ? ' st-bad' : ''}`}>
      <span className="rg-fl">{label}</span>
      {children}
      {hint && <small className="hint">{hint}</small>}
      {bad && <small className="st-err" role="alert">{bad}</small>}
    </div>
  )
}

/** Остаток: крупно — в единицах расхода (решение Олега 14.11), мелко — в упаковках. */
export function Rest({ it }: { it: Item }) {
  const cls = `st-rest${it.neg ? ' neg' : it.low ? ' low' : ''}`
  const units = qtyText(it.qty_milli, it.unit)
  if (it.pack_qty_milli <= 1000 || it.neg) return <span className={cls}><b>{units}</b></span>
  return <span className={cls}><b>{units}</b><small>{packText(it.qty_milli, it)}</small></span>
}

/** Значки строки: минус, ниже порога или «comandat», дорогое — на пациента с лотом. */
export function Flags({ it }: { it: Item }) {
  const o = it.ordered
  const st = orderState(o)
  return (
    <span className="st-flags">
      {it.neg && <span className="st-pill bad"><Icon name="sos" /> Pe minus</span>}
      {!it.neg && it.low && st !== 'on' && <span className="st-pill warn"><Icon name="excl" /> De comandat</span>}
      {it.low && o && st === 'on' && <span className="st-pill mute"><Icon name="check" /> comandat {dmy(o.on).slice(0, 5)}</span>}
      {it.low && o && st === 'late' && <span className="st-pill warn"><Icon name="hourglass" /> comandat acum {o.days} zile, n-a venit</span>}
      {it.costly && <span className="st-pill mute" title="Se scade pe pacient, cu numărul lotului">pe pacient · lot</span>}
    </span>
  )
}

export function Exp({ it }: { it: Item }) {
  if (!it.track_expiry && !it.exp_on) return <span className="st-mute">nu se cere</span>
  if (!it.exp_on || it.exp_days === null) return <span className="st-exp mute">—</span>
  const n = it.exp_days
  const cls = it.expired ? 'bad' : it.soon ? 'warn' : ''
  const word = it.expired ? `expirat de ${-n} z.` : n === 0 ? 'expiră azi' : it.soon ? `peste ${n} zile` : ''
  return <span className={`st-exp ${cls}`}><b>{dmy(it.exp_on)}</b>{word && <small>{word}</small>}</span>
}

const TONE: Record<Kind, string> = { intrare: 'ok', consum: 'info', casare: 'warn', inventar: 'mute', corectie: 'mute' }
export function KindPill({ m }: { m: Pick<Move, 'kind' | 'kind_label'> }) {
  return <span className={`st-pill ${TONE[m.kind]}`}>{m.kind_label}</span>
}

export function Signed({ q, unit }: { q: number; unit: string }) {
  return <span className={`st-q ${q > 0 ? 'in' : 'out'}`}>{q > 0 ? '+' : '-'}{num(Math.abs(q))} {unit}</span>
}

export function Empty({ ico = 'box', title, children }: { ico?: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="fcard rg-empty">
      <span className="rg-empty-ico"><Icon name={ico} /></span>
      <b>{title}</b>
      {children}
    </div>
  )
}
