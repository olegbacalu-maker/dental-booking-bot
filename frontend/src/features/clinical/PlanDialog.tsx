import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../../components/dialog'
import type { Odontogram, PlanAdd } from './chart'
import { PriceNote, priceAfterProcedure, serviceIdFor } from '../patients/card/planService'
import { ServicePicker } from '../patients/card/ServicePicker'
import { useLingering } from '../../utils/motion'

/* «Adaugă în plan» с зуба (01.10; Олег 27.09: «одонтограмма с планом не
   связана»). Врач смотрит на зуб — и кладёт процедуру в план, не уходя с
   дуги: номер подставлен, поля те же, что у формы плана фиши (процедура,
   врач, цена, срок), правила и тексты — сервера (`_add_plan`, `ok_card`).
   Открывается из меню зуба и из инспектора; путь не единственный — форма
   плана во вкладке «Plan și plăți» остаётся. Врач по умолчанию — тот, кто
   записал зуб (снапшот имени в фише зуба), если он ещё в списке. Цена — из
   прайса, когда процедуру взяли из него (`planService`). «Din șablon…» уводит
   в окно шаблонов клиники с этим же зубом — набор процедур вместо одной. */
const T = {
  title: 'Adaugă în plan',
  tooth: 'dintele',
  ph: { proc: 'Procedură (ex. Coroană zirconiu)', price: 'Preț MDL', due: 'Termen planificat', doctor: 'Medic —' },
  dueHint: 'termen (opțional)',
  save: 'Adaugă în plan',
  tpl: 'Din șablon…',
  tplTitle: 'Adaugă pe acest dinte un set de proceduri salvat ca șablon',
  close: 'Închide',
} as const

interface Props {
  model: Odontogram
  /** зуб, для которого открыт диалог; null — закрыт */
  n: number | null
  busy: boolean
  /** поле, которое сервер назвал виновным (`error.field`) */
  invalid: boolean
  onClose: () => void
  onSave: (body: PlanAdd) => Promise<boolean>
  /** «Din șablon…»: вместо одной процедуры — окно шаблонов с этим зубом. */
  onTemplate?: ((n: number) => void) | undefined
}

const EMPTY = { procedure: '', doctor: '', price: '', due_date: '' }

export function PlanDialog({ model, n, busy, invalid, onClose, onSave, onTemplate }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const first = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState(EMPTY)
  const [auto, setAuto] = useState(false)
  const services = model.services ?? []
  // новый зуб — чистая форма с его врачом; выводится при отрисовке, без эффекта
  const [seen, setSeen] = useState<number | null>(null)
  /* окно гаснет за ступень (07.11): номер зуба и подпись стоят до конца */
  const { shown: nShown } = useLingering(n)
  const info = nShown !== null ? model.teeth[String(nShown)] : undefined
  if (n !== null && n !== seen) {
    setSeen(n)
    const own = info?.doctor && model.doctors.includes(info.doctor) ? info.doctor : ''
    setForm({ ...EMPTY, doctor: own })
    setAuto(false)
  }
  const set = (patch: Partial<typeof EMPTY>) => setForm((f) => ({ ...f, ...patch }))

  /* фокус — в процедуру при ОТКРЫТИИ: `showModal` сам ставит его на первый
     фокусируемый узел (крестик), а врач пришёл печатать. ⛔ Не `autoFocus`:
     React зовёт focus() при монтаже, то есть при ЗАКРЫТОМ диалоге, и уводил бы
     фокус с вкладок фиши в невидимое поле. */
  useEffect(() => {
    if (n !== null) {
      showDialog(ref.current)
      first.current?.focus()
    } else hideDialog(ref.current)
  }, [n])

  function onProcedure(value: string) {
    const p = priceAfterProcedure(services, form.procedure, value, { price: form.price, auto })
    setAuto(p.auto)
    set({ procedure: value, price: p.price })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (n === null) return
    const ok = await onSave({ tooth: String(n), ...form,
                              service_id: serviceIdFor(services, form.procedure) })
    if (ok) setSeen(null)
  }

  return (
    <dialog ref={ref} className="dp-plan-dlg" onClose={onClose}>
      <div className="dlg-head">
        <span><Icon name="clipboard" /> {T.title} · {T.tooth} <b>{nShown ?? '—'}</b></span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form" onSubmit={onSubmit}>
        {info && <p className="hint dp-m0">{info.title}</p>}
        <ServicePicker inputRef={first} value={form.procedure} services={services} onChange={onProcedure}
               placeholder={T.ph.proc} label={T.ph.proc} maxLength={120} required invalid={invalid} />
        <select value={form.doctor} onChange={(e) => set({ doctor: e.target.value })} aria-label={T.ph.doctor}>
          <option value="">{T.ph.doctor}</option>
          {model.doctors.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input type="number" min={0} max={1000000} value={form.price}
               onChange={(e) => { setAuto(false); set({ price: e.target.value }) }}
               placeholder={T.ph.price} aria-label={T.ph.price} aria-describedby="dp-plan-dlg-price" />
        <PriceNote id="dp-plan-dlg-price" services={services} procedure={form.procedure} price={form.price} />
        <label className="dlab">{T.dueHint}
          <input type="date" value={form.due_date} onChange={(e) => set({ due_date: e.target.value })} aria-label={T.ph.due} />
        </label>
        <button disabled={busy}><Icon name="plus" /> {T.save}</button>
        {onTemplate && n !== null && (
          <button type="button" className="mv-no" title={T.tplTitle} onClick={() => onTemplate(n)}>
            <Icon name="clipboard" /> {T.tpl}
          </button>
        )}
      </form>
    </dialog>
  )
}
