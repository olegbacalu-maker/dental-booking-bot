import { Icon } from '../../components/Icon'
import type { LabHost } from './host'
import { dm, type NextAppt, type OrderRow, type Status, type Step } from './lab'

const UP = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const DOWN = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

/** Формула FDI: в окне — выбор, в остальных местах — отметка. */
export function TeethGrid({ value, onPick }: { value: number[]; onPick?: ((n: number) => void) | undefined }) {
  const row = (ns: number[]) => (
    <div className="lb-trow">
      {ns.map((n, i) => {
        const on = value.includes(n)
        const cls = `lb-t${on ? ' on' : ''}${i === 8 ? ' mid' : ''}`
        return onPick
          ? <button key={n} type="button" className={cls} aria-pressed={on} onClick={() => onPick(n)}>{n}</button>
          : <span key={n} className={cls}>{n}</span>
      })}
    </div>
  )
  return <div className="lb-teeth" role={onPick ? 'group' : undefined} aria-label="Dinți">{row(UP)}{row(DOWN)}</div>
}

/** Тон стадии — цвета смысла программы, не темы: у техника нейтрально, забрать — жёлтый, у нас — зелёный, примерка — синий. */
export const TONE: Record<Status, string> = {
  trimis: 'mute', gata: 'warn', primit: 'ok', proba: 'info', finalizat: 'done', anulat: 'off',
}

export function StatusPill({ o }: { o: Pick<OrderRow, 'status' | 'status_label' | 'late' | 'stage'> }) {
  const closed = o.status === 'finalizat' || o.status === 'anulat'
  return (
    <span className={`lb-st ${o.late ? 'bad' : TONE[o.status]}`} data-st={o.status}>
      {o.late ? <><Icon name="sos" /> Întârziat</> : o.status_label}
      {o.stage > 1 && !closed && <small> · etapa {o.stage}</small>}
    </span>
  )
}

/** Срок словами: сколько дней осталось или просрочено — число считает сервер. */
export function Due({ o }: { o: OrderRow }) {
  if (o.status === 'finalizat' || o.status === 'anulat') return <span className="lb-due mute">{dm(o.done_on || o.due_on)}</span>
  if (o.status !== 'trimis' && o.status !== 'gata') return <span className="lb-due mute">{dm(o.received_on || o.due_on)}</span>
  const n = o.due_in
  const word = n == null ? '' : n === 0 ? 'azi' : n === 1 ? 'mâine' : n > 1 ? `peste ${n} zile` : n === -1 ? 'ieri' : `${-n} zile în urmă`
  return (
    <span className={`lb-due${o.late ? ' bad' : n === 0 || n === 1 ? ' warn' : ''}`}>
      <b>{dm(o.due_on)}</b> {word && <small>{word}</small>}
    </span>
  )
}

/** Ближайший визит пациента; красным — если он сегодня или завтра, а работа ещё не в клинике. */
export function Appt({ a, warn }: { a: NextAppt | null; warn: boolean }) {
  if (!a) return <span className="lb-appt mute">—</span>
  return (
    <span className={`lb-appt${warn ? ' bad' : ''}`} title={warn ? `${a.doctor} · lucrarea nu e încă în clinică` : a.doctor}>
      {warn && <Icon name="sos" />}
      <b>{a.day === 'azi' ? 'azi' : a.day === 'maine' ? 'mâine' : dm(a.date)}</b> <small>{a.time}</small>
    </span>
  )
}

export function UrgentTag() {
  return <span className="lb-urgent">Urgent</span>
}

export const teethText = (t: number[]): string => (t.length ? t.join(', ') : '—')

const STEP_ICON: Partial<Record<Step['act'], Parameters<typeof Icon>[0]['name']>> = {
  gata: 'check', primit: 'door', proba: 'tooth', finalizat: 'check', etapa: 'undo', refacere: 'excl',
}

/** Кнопки строки: главный шаг и (после примерки) этап или переделка — как их назвал сервер; наряд; окно. */
export function RowActs({ o, host }: { o: OrderRow; host: LabHost }) {
  const steps = (o.steps ?? []).filter((s) => s.main || s.act === 'etapa' || s.act === 'refacere')
  return (
    <span className="lb-act">
      {steps.map((s) => (
        <button key={s.act} type="button" className={`lb-go${s.main ? '' : ' alt'}${s.act === 'finalizat' ? ' fin' : ''}`}
          disabled={host.busy} onClick={() => host.act(o, s.act)}>
          <Icon name={STEP_ICON[s.act] ?? 'check'} /> {s.label}
        </button>
      ))}
      <button type="button" className="lb-ib" title="Fișa de comandă" aria-label={`Tipărește fișa de comandă nr. ${o.nr}`}
        onClick={() => host.print(o.id)}><Icon name="print" /></button>
      <button type="button" className="lb-ib" title="Deschide comanda" aria-label={`Deschide comanda nr. ${o.nr}`}
        onClick={() => host.open(o.id)}><Icon name="pen" /></button>
    </span>
  )
}
