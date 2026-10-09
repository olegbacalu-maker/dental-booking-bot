import { useState, type FormEvent } from 'react'
import { ask } from '../../../components/confirm'
import { Icon, iconName } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type Alert, type PatientCard } from './card'

/* «Atenționări medicale» по макету (08.10): пустое состояние пунктиром, список
   плашек с кнопкой удаления 44px, выбор типа + поле + «Adaugă atenționare»
   (заперта, пока поле пустое). Типы — с сервера (`alert_kinds`); цвет плашки —
   по типу (аллергия — красный, лекарство — янтарный), не одним цветом.
   ⭐ С 09.10 блок СВОДНЫЙ (разбор: полоса в шапке показывала болезни из
   анамнеза, а блок писал «Nicio atenționare» — два противоречащих сообщения):
   после ручных пометок — риски анамнеза (галочки и свободный текст, те же, что
   в полосе шапки), серыми, без удаления — правятся в самом опроснике, куда
   ведёт «Anamneză ›». На вкладке «Date pacient» блок стоит под опросником и
   риски анамнеза не повторяет (`withAnamneza={false}`) — они рядом. */
const T = {
  title: 'Atenționări medicale',
  empty: 'Nicio atenționare înregistrată.',
  fromAnam: 'Din anamneză',
  editAnam: 'Modifică în Anamneză ›',
  anamHint: 'Din chestionarul de anamneză — se modifică acolo',
  kind: 'Tip atenționare',
  ph: 'ex. Alergie: Penicilină',
  add: 'Adaugă atenționare',
  del: 'Șterge',
  confirmDel: 'Ștergeți atenționarea „{what}"? Medicul nu o va mai vedea în fișă.',
} as const

interface Props {
  card: PatientCard
  a: CardActions
  /** Открыть опросник анамнеза (вкладка «Date pacient»); без него ссылки нет. */
  onAnamneza?: (() => void) | undefined
  /** Показывать ли риски анамнеза под пометками (на вкладке с опросником — нет). */
  withAnamneza?: boolean
}

export function AlertsCard({ card, a, onAnamneza, withAnamneza = true }: Props) {
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

  const an = card.anamneza
  const anRows = withAnamneza
    ? [...an.marked.map((m) => ({ k: `m:${m}`, head: '', text: m })),
       ...an.free.map((f) => ({ k: `f:${f.short}`, head: f.short, text: f.text }))]
    : []
  return (
    <div className="fcard dp-alerts">
      <h3>{T.title}</h3>
      {card.alerts.length === 0 && anRows.length === 0 && <p className="dp-aempty">{T.empty}</p>}
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
      ) : null}
      {anRows.length > 0 && (
        <div className="dp-alist dp-anam">
          <div className="dp-anam-h">
            <span>{T.fromAnam}</span>
            {onAnamneza && <button type="button" className="hero-risk-go" onClick={onAnamneza}>{T.editAnam}</button>}
          </div>
          {anRows.map((r) => (
            <div key={r.k} className="alert anam" title={T.anamHint}>
              <Icon name="note" />
              <span>{r.head ? <><b>{r.head}:</b> {r.text}</> : r.text}</span>
            </div>
          ))}
        </div>
      )}
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
