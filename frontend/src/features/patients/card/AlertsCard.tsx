import { useState, type FormEvent } from 'react'
import { Icon, iconName } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type PatientCard } from './card'

const T = {
  title: 'Atenționări medicale',
  empty: '— fără atenționări —',
  ph: 'ex. Alergie: Penicilină',
  add: '+ Adaugă',
  del: 'Șterge',
} as const

interface Props {
  card: PatientCard
  a: CardActions
}

export function AlertsCard({ card, a }: Props) {
  const kinds = card.options.alert_kinds
  const [kind, setKind] = useState(kinds[0]?.id ?? 'allergy')
  const [text, setText] = useState('')
  const [invalid, setInvalid] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setInvalid(false)
    const err = await a.act(() => patientCard.addAlert(a.pid, a.views, kind, text))
    if (err?.field) setInvalid(true)
    else if (!err) setText('')
  }

  return (
    <div className="fcard">
      <h3>{T.title}</h3>
      {card.alerts.length ? card.alerts.map((al) => (
        <div key={al.id} className={`alert ${al.kind}`}>
          <Icon name={iconName(al.icon)} /> {al.label} {al.text}
          <form onSubmit={(e) => { e.preventDefault(); void a.act(() => patientCard.delAlert(a.pid, a.views, al.id)) }}>
            <button title={T.del} aria-label={`${T.del}: ${al.text}`} disabled={a.busy}><Icon name="close" /></button>
          </form>
        </div>
      )) : <p className="hint dp-m0">{T.empty}</p>}
      <form className="fform dp-mt9" onSubmit={onSubmit}>
        <div className="r2">
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label={T.title} style={{ width: 130 }}>
            {kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={T.ph} aria-label={T.ph}
                 maxLength={120} required aria-invalid={invalid || undefined} />
        </div>
        <button disabled={a.busy}>{T.add}</button>
      </form>
    </div>
  )
}
