import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ask } from '../../../components/confirm'
import { Icon } from '../../../components/Icon'
import { useFormTouched, type CardActions } from './actions'
import { patientCard, type PatientCard, type PlanEdit, type PlanItem } from './card'
import { showDialog, useDialogLeave } from './dialog'
import { PriceNote, priceAfterProcedure, priceIsListed, serviceIdFor, ServiceList } from './planService'

/* «Editează» позиции плана: зуб, процедура, врач, цена, срок — пока позиция
   «Planificat» (после «Începe» она медзапись; порог держит сервер и отвечает
   словами). Уходит только изменённое: поле, которого нет в запросе, сервер не
   трогает, поэтому нетронутое окно ничего не шлёт, и «Salvează» в нём выключена.
   Отказ показывается в окне: модальное окно лежит поверх плашки экрана. */
const T = {
  title: 'Editează procedura',
  tooth: 'Dinte',
  noTooth: '— fără dinte —',
  milk: 'Dinți de lapte',
  proc: 'Procedură',
  doctor: 'Medic',
  noDoctor: '— fără medic —',
  price: 'Preț, MDL',
  due: 'Termen planificat',
  hint: 'Se poate modifica doar cât procedura e „Planificat”.',
  save: 'Salvează',
  cancel: 'Renunță',
  close: 'Închide',
  askLeave: 'Renunțați la modificările procedurii? Nu se salvează.',
  askOk: 'Renunță',
  askKeep: 'Continuă editarea',
} as const

interface Props {
  card: PatientCard
  a: CardActions
  it: PlanItem
  onClose: () => void
}

type Draft = Required<Omit<PlanEdit, 'service_id'>>

const draftOf = (it: PlanItem): Draft => ({
  tooth: it.tooth ? String(it.tooth) : '',
  procedure: it.procedure,
  doctor: it.doctor,
  price: it.price === null ? '' : String(it.price),
  due_date: it.due_date,
})

export function PlanEditDialog({ card, a, it, onClose }: Props) {
  const dlg = useRef<HTMLDialogElement>(null)
  const services = card.appoint.services
  const [base] = useState(() => draftOf(it))
  const [form, setForm] = useState(base)
  /* цена позиции равна прайсу — смена услуги ведёт её за собой, как в новой строке */
  const [auto, setAuto] = useState(() => priceIsListed(services, base.procedure, base.price))
  const [bad, setBad] = useState('')
  const [err, setErr] = useState('')
  const set = (patch: Partial<Draft>) => setForm((f) => ({ ...f, ...patch }))
  const keys = (Object.keys(base) as (keyof Draft)[])
  const touched = keys.filter((k) => (k === 'procedure' ? form[k].trim() : form[k]) !== base[k])
  const { leave: close, leaving } = useDialogLeave(dlg, onClose)
  /* закрытое окно доигрывает переход: несохранённого в нём уже нет */
  useFormTouched(a, 'planEdit', touched.length > 0 && !leaving)

  useEffect(() => { showDialog(dlg.current) }, [])

  function onProcedure(value: string) {
    const p = priceAfterProcedure(services, form.procedure, value, { price: form.price, auto })
    setAuto(p.auto)
    set({ procedure: value, price: p.price })
  }

  async function leave() {
    if (touched.length > 0 && !await ask({ text: T.askLeave, ok: T.askOk, cancel: T.askKeep })) return
    close()
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBad('')
    setErr('')
    const body: PlanEdit = {}
    for (const k of touched) body[k] = k === 'procedure' ? form[k].trim() : form[k]
    if (body.procedure !== undefined) body.service_id = serviceIdFor(services, body.procedure)
    const failed = await a.act(() => patientCard.editPlan(a.pid, a.views, it.id, body))
    if (failed) {
      setBad(failed.field ?? '')
      setErr(failed.text)
      return
    }
    close()
  }

  const doctors = card.options.doctors
  return (
    <dialog ref={dlg} className="dp-plan-edit" aria-label={T.title}
      onCancel={(e) => { e.preventDefault(); void leave() }}>
      <div className="dlg-head">
        <span><Icon name="pen" /> {T.title}</span>
        <button type="button" onClick={() => { void leave() }} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form" onSubmit={onSubmit}>
        <label className="dlab">{T.proc}
          <input value={form.procedure} onChange={(e) => onProcedure(e.target.value)} maxLength={120} required
                 aria-invalid={bad === 'procedure' || undefined} list="dp-plan-edit-services" />
        </label>
        <ServiceList id="dp-plan-edit-services" services={services} />
        <div className="pe-row">
          <label className="dlab">{T.tooth}
            <select value={form.tooth} onChange={(e) => set({ tooth: e.target.value })}
                    aria-invalid={bad === 'tooth' || undefined}>
              <option value="">{T.noTooth}</option>
              {card.options.teeth.map((n) => <option key={n} value={n}>{n}</option>)}
              <optgroup label={T.milk}>
                {card.options.milk.map((n) => <option key={n} value={n}>{n}</option>)}
              </optgroup>
            </select>
          </label>
          <label className="dlab">{T.doctor}
            <select value={form.doctor} onChange={(e) => set({ doctor: e.target.value })}>
              <option value="">{T.noDoctor}</option>
              {/* врач позиции, которого уже нет в списке, остаётся выбранным: иначе
                  поле показало бы «без врача» у позиции с врачом */}
              {base.doctor && !doctors.includes(base.doctor) && <option value={base.doctor}>{base.doctor}</option>}
              {doctors.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <div className="pe-row">
          <label className="dlab">{T.price}
            <input type="number" min={0} max={1000000} value={form.price} aria-describedby="dp-plan-edit-price"
                   aria-invalid={bad === 'price' || undefined}
                   onChange={(e) => { setAuto(false); set({ price: e.target.value }) }} />
          </label>
          <label className="dlab">{T.due}
            <input type="date" value={form.due_date} onChange={(e) => set({ due_date: e.target.value })}
                   aria-invalid={bad === 'due_date' || undefined} />
          </label>
        </div>
        {/* строка под подсказку прайса занята всегда: подсказка приходит и уходит с каждой буквой процедуры,
            а окно стоит по центру — без места под неё оно меняло бы высоту при наборе */}
        <div className="pe-note">
          <PriceNote id="dp-plan-edit-price" services={services} procedure={form.procedure} price={form.price} />
        </div>
        {err
          ? <p className="pe-err" role="alert"><Icon name="excl" /> {err}</p>
          : <p className="hint dp-m0">{T.hint}</p>}
        <div className="pe-foot">
          <button type="button" className="mv-no" onClick={() => { void leave() }}>{T.cancel}</button>
          <button disabled={a.busy || touched.length === 0}><Icon name="check" /> {T.save}</button>
        </div>
      </form>
    </dialog>
  )
}
