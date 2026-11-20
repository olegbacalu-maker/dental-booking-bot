import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ask } from '../../../components/confirm'
import { Icon } from '../../../components/Icon'
import { useFormTouched, type CardActions } from './actions'
import { mdl, patientCard, type PatientCard } from './card'
import { showDialog, useDialogLeave } from './dialog'

/* «Salvează ca șablon»: отмеченные позиции плана пациента становятся шаблоном
   клиники. В шаблон идут процедура, «нужен зуб» и порядок плана; цены — только
   по галочке. О пациенте в шаблон не попадает ничего — ни номера зубов, ни
   врач, ни срок, ни причина отказа: что именно уезжает, собирает сервер, окно
   шлёт только номера позиций. Кнопку окна видит тот, кому сервер назвал право
   (`plan.can_template`); сервер проверяет его сам. */
const T = {
  title: 'Salvează ca șablon',
  close: 'Închide',
  name: 'Numele șablonului',
  namePh: 'de exemplu: Implant + coroană',
  pick: 'Procedurile care intră în șablon',
  withTooth: 'cu dinte',
  noTooth: 'fără dinte',
  keep: 'Păstrează prețurile',
  keepHint: 'Fără bifă, prețul se ia din lista de prețuri în ziua în care adăugați șablonul.',
  what: 'Se păstrează procedurile și ordinea lor.',
  never: 'Nimic despre pacient nu intră în șablon: nici dinții, nici medicul, nici notițele.',
  save: 'Salvează șablonul',
  cancel: 'Renunță',
  mdl: 'MDL',
  askLeave: 'Renunțați la șablon? Nu se salvează.',
  askOk: 'Renunță',
  askKeep: 'Continuă',
} as const

interface Props {
  card: PatientCard
  a: CardActions
  onClose: () => void
}

export function PlanSaveTemplateDialog({ card, a, onClose }: Props) {
  const dlg = useRef<HTMLDialogElement>(null)
  const items = card.plan.items
  /* отказанное в шаблон по умолчанию не идёт: от него пациент отказался */
  const [base] = useState(() => items.filter((it) => it.status !== 'refuzat').map((it) => it.id))
  const [name, setName] = useState('')
  const [ids, setIds] = useState(base)
  const [keep, setKeep] = useState(false)
  const [bad, setBad] = useState('')
  const [err, setErr] = useState('')
  const { leave: close, leaving } = useDialogLeave(dlg, onClose)
  /* закрытое окно доигрывает переход: несохранённого в нём уже нет */
  const touched = name.trim() !== '' && !leaving
  useFormTouched(a, 'planSave', touched)

  useEffect(() => { showDialog(dlg.current) }, [])

  async function leave() {
    if (touched && !await ask({ text: T.askLeave, ok: T.askOk, cancel: T.askKeep })) return
    close()
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBad('')
    setErr('')
    const failed = await a.act(() => patientCard.planSaveTemplate(a.pid, a.views,
      { name: name.trim(), item_ids: items.filter((it) => ids.includes(it.id)).map((it) => it.id), keep_prices: keep }))
    if (failed) {
      setBad(failed.field ?? '')
      setErr(failed.text)
      return
    }
    close()
  }

  return (
    <dialog ref={dlg} className="dp-plan-tpl save" aria-label={T.title}
      onCancel={(e) => { e.preventDefault(); void leave() }}>
      <div className="dlg-head">
        <span><Icon name="save" /> {T.title}</span>
        <button type="button" onClick={() => { void leave() }} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="tp-save" onSubmit={onSubmit}>
        <label className="tp-lab">{T.name}
          <input className="dp-fld" value={name} maxLength={60} required placeholder={T.namePh}
            aria-invalid={bad === 'name' || undefined}
            onChange={(e) => { setName(e.target.value); setBad('') }} />
        </label>
        <fieldset className="tp-pick" aria-invalid={bad === 'rows' || undefined}>
          <legend>{T.pick}</legend>
          {items.map((it) => (
            <label key={it.id} className="tp-proc">
              <input type="checkbox" checked={ids.includes(it.id)}
                onChange={(e) => setIds((x) => (e.target.checked ? [...x, it.id] : x.filter((i) => i !== it.id)))} />
              <span>{it.procedure}</span>
              <small>
                {it.tooth ? T.withTooth : T.noTooth}
                {keep && it.price !== null ? ` · ${mdl(it.price)} ${T.mdl}` : ''}
                {it.status === 'refuzat' ? ` · ${it.label}` : ''}
              </small>
            </label>
          ))}
        </fieldset>
        <label className="tp-proc tp-keep">
          <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
          <span>{T.keep}</span>
        </label>
        <p className="hint dp-m0">{T.keepHint}</p>
        <p className="hint dp-m0">{T.what} <b>{T.never}</b></p>
        {err && <p className="tp-err" role="alert"><Icon name="excl" /> {err}</p>}
        <div className="tp-foot">
          <button type="button" className="dp-btn" onClick={() => { void leave() }}>{T.cancel}</button>
          <button className="dp-btn pri" disabled={a.busy || ids.length === 0}><Icon name="save" /> {T.save}</button>
        </div>
      </form>
    </dialog>
  )
}
