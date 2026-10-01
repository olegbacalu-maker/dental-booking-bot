import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../../components/dialog'
import type { Odontogram, PlanAdd } from './chart'

/* «Adaugă în plan» с зуба (01.10; Олег 27.09: «одонтограмма с планом не
   связана»). Врач смотрит на зуб — и кладёт процедуру в план, не уходя с
   дуги: номер подставлен, поля те же, что у формы плана фиши (процедура,
   врач, цена, срок), правила и тексты — сервера (`_add_plan`, `ok_card`).
   Открывается из меню зуба и из инспектора; путь не единственный — форма
   плана во вкладке «Plan și plăți» остаётся. Врач по умолчанию — тот, кто
   записал зуб (снапшот имени в фише зуба), если он ещё в списке. */
const T = {
  title: 'Adaugă în plan',
  tooth: 'dintele',
  ph: { proc: 'Procedură (ex. Coroană zirconiu)', price: 'Preț MDL', due: 'Termen planificat', doctor: 'Medic —' },
  dueHint: 'termen (opțional)',
  save: 'Adaugă în plan',
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
}

const EMPTY = { procedure: '', doctor: '', price: '', due_date: '' }

export function PlanDialog({ model, n, busy, invalid, onClose, onSave }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const first = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState(EMPTY)
  // новый зуб — чистая форма с его врачом; выводится при отрисовке, без эффекта
  const [seen, setSeen] = useState<number | null>(null)
  const info = n !== null ? model.teeth[String(n)] : undefined
  if (n !== null && n !== seen) {
    setSeen(n)
    const own = info?.doctor && model.doctors.includes(info.doctor) ? info.doctor : ''
    setForm({ ...EMPTY, doctor: own })
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

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (n === null) return
    const ok = await onSave({ tooth: String(n), ...form })
    if (ok) setSeen(null)
  }

  return (
    <dialog ref={ref} className="dp-plan-dlg" onClose={onClose}>
      <div className="dlg-head">
        <span><Icon name="clipboard" /> {T.title} · {T.tooth} <b>{n ?? '—'}</b></span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form" onSubmit={onSubmit}>
        {info && <p className="hint dp-m0">{info.title}</p>}
        <input ref={first} value={form.procedure} onChange={(e) => set({ procedure: e.target.value })} placeholder={T.ph.proc}
               aria-label={T.ph.proc} maxLength={120} required aria-invalid={invalid || undefined} />
        <select value={form.doctor} onChange={(e) => set({ doctor: e.target.value })} aria-label={T.ph.doctor}>
          <option value="">{T.ph.doctor}</option>
          {model.doctors.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input type="number" min={0} max={1000000} value={form.price} onChange={(e) => set({ price: e.target.value })}
               placeholder={T.ph.price} aria-label={T.ph.price} />
        <label className="dlab">{T.dueHint}
          <input type="date" value={form.due_date} onChange={(e) => set({ due_date: e.target.value })} aria-label={T.ph.due} />
        </label>
        <button disabled={busy}><Icon name="plus" /> {T.save}</button>
      </form>
    </dialog>
  )
}
