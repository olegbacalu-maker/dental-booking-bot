import { useState, type FormEvent } from 'react'
import { Icon, iconName } from '../../../components/Icon'
import type { CardActions } from './actions'
import { mdl, patientCard, type PatientCard } from './card'

/* «Plăți și sold»: долг = финализированные позиции плана с ценой минус
   платежи (считает сервер). Записывает любая роль, удаляет директор —
   кнопку показывает сервер (can_delete), решает — тоже он (403). */
const T = {
  title: 'Plăți și sold',
  charged: 'lucrări finalizate:',
  paid: 'plătit:',
  debt: 'De achitat',
  advance: 'Avans',
  sold: 'Sold',
  paidUp: 'achitat integral',
  empty: '— încă fără plăți —',
  delTitle: 'Șterge plata (doar director)',
  confirmDel: 'Ștergeți plata? Rămâne urmă în istoricul fișei.',
  ph: { amount: 'Suma MDL (cu minus = restituire)', note: 'Notă (opțional, ex. avans coroană)' },
  method: 'Metoda',
  add: '＋ Înregistrează plata',
  hint1: 'Soldul = lucrările ',
  hint1b: 'finalizate',
  hint1c: ' din plan (cu preț) minus plățile. Plata nu se leagă de o procedură anume — banii acoperă soldul fișei.',
  mdl: 'MDL',
} as const

interface Props {
  card: PatientCard
  a: CardActions
}

export function FinanceCard({ card, a }: Props) {
  const fin = card.finance
  const methods = card.options.pay_methods
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState(methods[0]?.id ?? 'numerar')
  const [note, setNote] = useState('')
  const [invalid, setInvalid] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setInvalid(false)
    const err = await a.act(() => patientCard.addPayment(a.pid, a.views, amount, method, note))
    if (err?.field) setInvalid(true)
    else if (!err) { setAmount(''); setNote('') }
  }

  async function del(id: number) {
    if (!window.confirm(T.confirmDel)) return
    await a.act(() => patientCard.delPayment(a.pid, a.views, id))
  }

  const sold = fin.sold
  return (
    <div className="fcard" id="plati">
      <h3>{T.title} <small>· {T.charged} {mdl(fin.charged)} {T.mdl} · {T.paid} {mdl(fin.paid)} {T.mdl}</small></h3>
      {sold?.kind === 'bad' && <div className="sold bad"><span>{T.debt}</span><b>{mdl(sold.amount)} {T.mdl}</b></div>}
      {sold?.kind === 'plus' && <div className="sold plus"><span>{T.advance}</span><b>{mdl(sold.amount)} {T.mdl}</b></div>}
      {sold?.kind === 'ok' && <div className="sold ok"><span>{T.sold}</span><b>{T.paidUp}</b></div>}
      {fin.payments.length ? fin.payments.map((pl) => (
        <div key={pl.id} className={`pay-row${pl.neg ? ' neg' : ''}`}>
          <span className="pw">{pl.when}</span>
          <span className="pi" title={pl.method}><Icon name={iconName(pl.icon)} /></span>
          <b className="pa">{pl.neg ? '- ' : ''}{mdl(pl.amount)} {T.mdl}</b>
          <span className="pn">{pl.note}{pl.taken_by ? ` · ${pl.taken_by}` : ''}</span>
          {fin.can_delete && (
            <form onSubmit={(e) => { e.preventDefault(); void del(pl.id) }}>
              <button title={T.delTitle} aria-label={`${T.delTitle}: ${pl.when}`} disabled={a.busy}><Icon name="close" /></button>
            </form>
          )}
        </div>
      )) : <p className="hint dp-m6">{T.empty}</p>}
      <form className="fform dp-mt10" onSubmit={onSubmit}>
        <div className="r2">
          <input type="number" required min={-1000000} max={1000000} value={amount}
                 onChange={(e) => setAmount(e.target.value)} placeholder={T.ph.amount} aria-label={T.ph.amount}
                 aria-invalid={invalid || undefined} />
          <select value={method} onChange={(e) => setMethod(e.target.value)} aria-label={T.method} style={{ width: 160 }}>
            {methods.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
          </select>
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={T.ph.note} aria-label={T.ph.note} maxLength={120} />
        <button disabled={a.busy}>{T.add}</button>
      </form>
      <p className="hint dp-mt8">{T.hint1}<b>{T.hint1b}</b>{T.hint1c}</p>
    </div>
  )
}
