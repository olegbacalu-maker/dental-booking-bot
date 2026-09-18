import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { hideDialog, showDialog } from './dialog'
import { patientCard, type Appoint } from './card'

/* Запись ДЛЯ ЭТОГО пациента: услуга решает, кто из врачей её выполняет;
   дата и врач решают, какие часы свободны — часы спрашиваются у того же
   движка, что обслуживает бота. Ответ на устаревший запрос не показывается:
   смена услуги/врача/даты обрывает запрос в полёте, а пришедший список
   принимается только для того ключа, который спрашивали. */
const T = {
  title: 'Programare —',
  service: 'Serviciu',
  doctor: 'Medic',
  date: 'Data',
  time: 'Ora — doar intervalele libere',
  noDoctor: 'Niciun medic activ pentru acest serviciu.',
  loading: 'Caut orele libere…',
  free: 'intervale libere în această zi',
  none: 'Nicio oră liberă — alegeți altă zi sau alt medic.',
  failed: 'Nu am putut încărca orele libere.',
  go: 'Adaugă programarea',
  close: 'Închide',
} as const

interface Props {
  open: boolean
  name: string
  appoint: Appoint
  a: CardActions
  onClose: () => void
}

interface Slots {
  key: string
  slots: string[]
  failed: boolean
}

export function AppointDialog({ open, name, appoint, a, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [service, setService] = useState(appoint.services[0]?.id ?? '')
  const [doctorPick, setDoctorPick] = useState('')
  const [date, setDate] = useState(appoint.today)
  const [timePick, setTimePick] = useState('')
  const [got, setGot] = useState<Slots | null>(null)

  /* врач: выбранный, если он делает услугу, иначе медик курант, иначе
     первый — как apRefresh(1) старой страницы; выводится при отрисовке */
  const doctors = appoint.doctors[service] ?? []
  const doctor = doctors.includes(doctorPick) ? doctorPick
    : doctors.includes(appoint.primary) ? appoint.primary : (doctors[0] ?? '')
  const doctorOk = doctor !== ''
  const key = `${date}|${doctor}|${service}`

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  useEffect(() => {
    if (!open || !doctorOk) return
    const ctl = new AbortController()
    patientCard.slots(a.pid, date, doctor, service, ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setGot({ key, slots: r.data.slots, failed: false }) },
      () => { if (!ctl.signal.aborted) setGot({ key, slots: [], failed: true }) },
    )
    return () => ctl.abort()
  }, [open, key, doctorOk, a.pid, date, doctor, service])

  const cur = got && got.key === key ? got : null
  const slots = cur?.slots ?? []
  const time = slots.includes(timePick) ? timePick : (slots[0] ?? '')
  const hint = !doctorOk ? T.noDoctor
    : cur === null ? T.loading
      : cur.failed ? T.failed
        : slots.length ? `${slots.length} ${T.free}` : T.none

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const err = await a.act(() => patientCard.appoint(a.pid, a.views, { date, time, doctor, service }))
    if (!err) onClose()
  }

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span><Icon name="cal" /> {T.title} {name || '—'}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form" onSubmit={onSubmit}>
        <label className="dlab">{T.service}
          <select value={service} onChange={(e) => setService(e.target.value)}>
            {appoint.services.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        <label className="dlab">{T.doctor}
          <select value={doctor} onChange={(e) => setDoctorPick(e.target.value)}>
            {doctors.map((dk) => <option key={dk} value={dk}>{appoint.names[dk] ?? dk}</option>)}
          </select>
        </label>
        <label className="dlab">{T.date}
          <input type="date" value={date} min={appoint.today} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="dlab">{T.time}
          <select value={time} onChange={(e) => setTimePick(e.target.value)} required>
            {slots.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
        <p className="hint dp-m0">{hint}</p>
        <button disabled={a.busy || !slots.length}>{T.go}</button>
      </form>
    </dialog>
  )
}
