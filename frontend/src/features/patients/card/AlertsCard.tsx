import { useState, type FormEvent } from 'react'
import { ask } from '../../../components/confirm'
import { Icon, iconName } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type Alert, type PatientCard } from './card'

/* «Atenționări medicale» по макету (08.10): пустое состояние пунктиром, список
   плашек с кнопкой удаления 44px, выбор типа + поле + «Adaugă atenționare»
   (заперта, пока поле пустое). Типы — с сервера (`alert_kinds`); цвет плашки —
   по типу (аллергия — красный, лекарство — янтарный), не одним цветом. */
const T = {
  title: 'Atenționări medicale',
  empty: 'Nicio atenționare înregistrată.',
  kind: 'Tip atenționare',
  ph: 'ex. Alergie: Penicilină',
  add: 'Adaugă atenționare',
  del: 'Șterge',
  confirmDel: 'Ștergeți atenționarea „{what}"? Medicul nu o va mai vedea în fișă.',
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

  /* удаление — только после вопроса своим окном (01.10): до того крестик
     стирал аллергию молча, одним щелчком */
  async function del(al: Alert) {
    if (!await ask({ text: T.confirmDel.replace('{what}', `${al.label}: ${al.text}`), danger: true })) return
    await a.act(() => patientCard.delAlert(a.pid, a.views, al.id))
  }

  return (
    <div className="fcard dp-alerts">
      <h3>{T.title}</h3>
      {card.alerts.length ? (
        <div className="dp-alist">
          {card.alerts.map((al) => (
            <div key={al.id} className={`alert ${al.kind}`}>
              <Icon name={iconName(al.icon)} />
              <span><b>{al.label}:</b> {al.text}</span>
              <form onSubmit={(e) => { e.preventDefault(); void del(al) }}>
                <button className="dp-ibtn" title={T.del} aria-label={`${T.del}: ${al.text}`} disabled={a.busy}><Icon name="close" /></button>
              </form>
            </div>
          ))}
        </div>
      ) : <p className="dp-aempty">{T.empty}</p>}
      <form className="dp-aform" onSubmit={onSubmit}>
        <div className="dp-aform-r">
          {/* ⚠️ aria-label списка — имя карточки: так его находят проверки и читалка */}
          <select className="dp-sel" value={kind} onChange={(e) => setKind(e.target.value)} aria-label={T.title}>
            {kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
          <input className="dp-fld" value={text} onChange={(e) => setText(e.target.value)} placeholder={T.ph} aria-label={T.ph}
                 maxLength={120} required aria-invalid={invalid || undefined} />
        </div>
        <button className="dp-btn pri" disabled={a.busy || !text.trim()}><Icon name="plus" /> {T.add}</button>
      </form>
    </div>
  )
}
