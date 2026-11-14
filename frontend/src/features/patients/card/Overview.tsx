import { Icon } from '../../../components/Icon'
import { roCount } from '../../../utils/plural'
import { dm, isOpen, type OrderRow } from '../../lab/lab'
import type { PatientLabModel } from '../../lab/PatientLab'
import { mdl, type PatientCard, type TodoItem } from './card'

/* Rezumat фиши: «De făcut» (что по пациенту ждёт человека) и четыре плитки «что дальше» — вместо пяти
   цифр «сколько» над всеми вкладками. Строки фиши считает сервер (`card.todo`), строки лаборатории —
   флаги заказа сервера (`late`, `visit_wait`); здесь только слова и кнопки. */
const T = {
  todo: 'De făcut',
  waiting: { one: '1 lucru așteaptă', few: '{n} lucruri așteaptă', many: '{n} de lucruri așteaptă' },
  proc: { one: '1 procedură', few: '{n} proceduri', many: '{n} de proceduri' },
  days: { one: '1 zi', few: '{n} zile', many: '{n} de zile' },
  debt: (m: string) => `De achitat ${m} MDL`,
  debtSub: 'lucrări finalizate din plan minus plățile',
  pay: 'Înregistrează plata',
  unsigned: 'Acordul la plan nu e semnat',
  stale: 'Planul s-a schimbat după semnarea acordului',
  signSub: (n: string, m: string) => `${n} · ${m} MDL — se semnează înainte de a începe`,
  openPlan: 'Deschide planul',
  noNext: 'Plan activ fără programare',
  noNextSub: (n: string) => `${n} în plan — nicio vizită programată`,
  book: 'Programează',
  recall: (s: string) => `Revenire întârziată: ${s}`,
  recallSub: (d: string, late: string) => `trebuia ~${d}${late ? ` · ${late}` : ''}`,
  labLate: (w: string, l: string, d: string) => `${w}${l ? ` · ${l}` : ''} — întârzie ${d}`,
  labWait: (w: string, l: string) => `${w}${l ? ` · ${l}` : ''} — lucrarea nu e în clinică`,
  labSub: (due: string, a: OrderRow['next_appt']) =>
    `termen ${due}${a ? ` · vizita e ${a.day ?? a.date.split('-').reverse().join('.')} la ${a.time}` : ''}`,
  openOrder: 'Deschide comanda',
  tiles: 'Pe scurt',
  next: 'Următoarea vizită',
  notBooked: 'neprogramat',
  plan: 'Plan de tratament',
  planOf: (d: number, n: number) => `${d} din ${n}`,
  planSum: (m: string) => `${m} MDL în plan activ`,
  planEmpty: 'planul este gol',
  sold: 'Sold',
  soldBad: 'de achitat',
  soldPlus: 'avans',
  soldOk: 'achitat integral',
  soldNone: 'fără lucrări facturate',
  lastPay: (w: string) => `ultima plată ${w}`,
  lab: 'Laborator',
  labOpen: (n: number) => `${n} în lucru`,
  labLateN: (n: number) => `${n} întârzie`,
  labDue: (d: string) => `următorul termen ${d}`,
  labNone: 'nimic în lucru',
} as const

export interface TodoRow {
  key: string
  tone: 'bad' | 'warn'
  icon: Parameters<typeof Icon>[0]['name']
  text: string
  sub: string
  btn: string
  run: () => void
}

interface Go {
  plan: () => void
  book: () => void
  order: (id: number) => void
}

/** Строки лаборатории: опаздывает или визит близко, а работы нет. */
export function labTodo(L: PatientLabModel, go: Go): TodoRow[] {
  return (L.data?.orders ?? []).filter((o) => isOpen(o) && (o.late || o.visit_wait)).map((o) => ({
    key: `lab-${o.id}`, tone: 'bad', icon: 'box',
    text: o.late ? T.labLate(o.work, o.lab, roCount(o.days_late ?? 0, T.days)) : T.labWait(o.work, o.lab),
    sub: T.labSub(dm(o.due_on), o.visit_wait ? o.next_appt : null),
    btn: T.openOrder, run: () => go.order(o.id),
  }))
}

function cardRow(t: TodoItem, go: Go): TodoRow {
  const n = roCount(t.n ?? 0, T.proc)
  const m = mdl(t.amount ?? 0)
  switch (t.code) {
    case 'debt':
      return { key: t.code, tone: t.tone, icon: 'money', text: T.debt(m), sub: T.debtSub, btn: T.pay, run: go.plan }
    case 'plan_unsigned':
    case 'plan_stale':
      return { key: t.code, tone: t.tone, icon: 'file', text: t.code === 'plan_stale' ? T.stale : T.unsigned,
        sub: T.signSub(n, m), btn: T.openPlan, run: go.plan }
    case 'no_next':
      return { key: t.code, tone: t.tone, icon: 'cal', text: T.noNext, sub: T.noNextSub(n), btn: T.book, run: go.book }
    case 'recall_late':
      return { key: t.code, tone: t.tone, icon: 'refresh', text: T.recall(t.service ?? ''),
        sub: T.recallSub(t.date ?? '', t.late ?? ''), btn: T.book, run: go.book }
  }
}

/** Все строки «De făcut»: красные (деньги, лаборатория) первыми, потом жёлтые — порядок сервера внутри тона. */
export function todoRows(card: PatientCard, L: PatientLabModel, go: Go): TodoRow[] {
  const rows = [...labTodo(L, go), ...card.todo.map((t) => cardRow(t, go))]
  return [...rows.filter((r) => r.tone === 'bad'), ...rows.filter((r) => r.tone === 'warn')]
}

export function TodoCard({ rows }: { rows: TodoRow[] }) {
  if (!rows.length) return null
  return (
    <div className="fcard dp-todo">
      <h3>{T.todo} <small>· {roCount(rows.length, T.waiting)}</small></h3>
      <ul>
        {rows.map((r) => (
          <li key={r.key} className={r.tone}>
            <span className="dp-todo-ic"><Icon name={r.icon} /></span>
            <span className="dp-todo-t"><b>{r.text}</b><small>{r.sub}</small></span>
            <button type="button" className="dp-btn" onClick={r.run}>{r.btn}</button>
          </li>
        ))}
      </ul>
    </div>
  )
}

interface Tile { key: string; label: string; value: string; sub: string; tone?: 'bad' | ''; bar?: number; run: () => void }

/** Четыре плитки «что дальше»: визит, план, сальдо, лаборатория (последняя — только если заказы были). */
export function SummaryTiles({ card, lab: L, go, onVisits }: { card: PatientCard; lab: PatientLabModel; go: Go; onVisits: () => void }) {
  const n = card.hero.next
  const pl = card.plan
  const s = card.finance.sold
  const pay = card.finance.payments[0]
  const tiles: Tile[] = [
    n ? { key: 'next', label: T.next, value: `${n.date.slice(0, 5)} · ${n.time}`, sub: [n.service, n.doctor].filter(Boolean).join(' · '), run: onVisits }
      : { key: 'next', label: T.next, value: '—', sub: T.notBooked, tone: pl.n_act ? 'bad' : '', run: go.book },
    pl.n_track
      ? { key: 'plan', label: T.plan, value: `${T.planOf(card.kpi.done, pl.n_track)} · ${pl.pct_done} %`, sub: T.planSum(mdl(pl.total)), bar: pl.pct_done, run: go.plan }
      : { key: 'plan', label: T.plan, value: '—', sub: T.planEmpty, run: go.plan },
    {
      key: 'sold', label: T.sold, run: go.plan,
      value: s ? `${mdl(s.amount)} MDL` : '—',
      sub: [s ? (s.kind === 'bad' ? T.soldBad : s.kind === 'plus' ? T.soldPlus : T.soldOk) : T.soldNone,
        pay ? T.lastPay(pay.when.slice(0, 10)) : ''].filter(Boolean).join(' · '),
      tone: s?.kind === 'bad' ? 'bad' : '',
    },
  ]
  const orders = L.data?.orders ?? []
  if (orders.length) {
    const open = orders.filter(isOpen)
    const late = open.filter((o) => o.late).length
    const due = open.map((o) => o.due_on).filter(Boolean).sort()[0]
    tiles.push({
      key: 'lab', label: T.lab, run: go.plan, value: T.labOpen(open.length),
      sub: !open.length ? T.labNone : late ? T.labLateN(late) : due ? T.labDue(dm(due)) : '',
      tone: late ? 'bad' : '',
    })
  }
  return (
    <div className="kpi5 dp-tiles" role="group" aria-label={T.tiles}>
      {tiles.map((t) => (
        <button key={t.key} type="button" className={`kpi t-${t.key}`} onClick={t.run}>
          <span className="kpi-l">{t.label}</span>
          <b className={t.tone || undefined}>{t.value}</b>
          {t.bar != null && <span className="dp-bar" aria-hidden="true"><i style={{ width: `${t.bar}%` }} /></span>}
          <small className={t.tone || undefined}>{t.sub}</small>
        </button>
      ))}
    </div>
  )
}
