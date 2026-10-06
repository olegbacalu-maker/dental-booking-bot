import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import type { DayForm, NewAppt } from './day'

/* «Programare nouă» окном (06.10, Олег: форма внизу страницы — старый облик,
   на панели новая запись открывается окном). Ручная запись по телефону и у
   стойки — то же, что делала нижняя форма журнала (C25.5b), и те же правила.

   ⛔ Врачи и часы — ИЗ `form`, а не из колонок канвы. На канве остаётся
   колонка выключенного врача, пока у него есть записи дня, а запись ответит
   ему `bad_off`: возьми список из колонок — регистратура выбрала бы такого
   врача и получила отказ на ровном месте.
   ⚠️ Смена врача переписывает список часов и СОХРАНЯЕТ выбранный час, если он
   есть и у нового, — ровно как DOC_TIMES на старой странице.
   ⚠️ Список часов один на все услуги (сервер считает его на 30 минут): у
   часовой услуги поздний старт отобьётся кодом `outside` — та же подсказка.
   ⛔ Окно закрывается ТОЛЬКО на удаче: отказ («interval ocupat») оставляет
   набранное на экране, как у окна свободного часа. */
const T = {
  title: 'Programare nouă',
  date: 'Data',
  time: 'Ora',
  doctor: 'Medic',
  service: 'Serviciu',
  noPhone: 'fără telefon',
  birth: 'Data nașterii (opț.)',
  go: 'Adaugă programarea',
  name: 'Nume pacient',
  phone: 'Telefon',
  close: 'Închide',
} as const

interface Props {
  open: boolean
  form: DayForm
  /** День экрана: подставляется в поле даты при открытии. ⛔ Экран ставит окну
   *  `key` по дню — смена дня начинает запись заново, как перезагрузка старой
   *  страницы (Олег 24.09). */
  date: string
  busy: boolean
  onClose: () => void
  onAdd: (body: NewAppt) => Promise<boolean>
}

export function AddDialog({ open, form, date, busy, onClose, onAdd }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [at, setAt] = useState(date)
  const [doctorPick, setDoctorPick] = useState('')
  const [timePick, setTimePick] = useState(form.time)
  const [service, setService] = useState(form.services[0]?.id ?? '')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')

  const doctor = form.times[doctorPick] ? doctorPick : form.doctor
  const times = form.times[doctor] ?? form.hours
  const time = times.includes(timePick) ? timePick : (times[0] ?? '')

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const ok = await onAdd({ date: at, time, doctor, service, name,
      phone: noPhone ? '' : phone, nophone: noPhone, birth })
    if (ok) onClose()
  }

  return (
    <dialog ref={ref} onClose={onClose} className="dp-adddlg">
      <div className="dlg-head">
        <span><Icon name="plus" /> {T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form dp-addform" onSubmit={submit}>
        <div className="dp-addrow">
          <label className="dlab">{T.date}
            <input type="date" value={at} onChange={(e) => setAt(e.target.value)} required />
          </label>
          <label className="dlab">{T.time}
            <select value={time} onChange={(e) => setTimePick(e.target.value)}>
              {times.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        </div>
        {form.doctors.length === 1
          ? <b className="dp-adddoc">{form.doctors[0]?.name}</b>
          : (
            <select value={doctor} onChange={(e) => setDoctorPick(e.target.value)}
                    aria-label={T.doctor}>
              {form.doctors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          )}
        <select value={service} onChange={(e) => setService(e.target.value)}
                aria-label={T.service}>
          {form.services.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder={T.name} required />
        <input value={noPhone ? '' : phone} onChange={(e) => setPhone(e.target.value)}
               placeholder={T.phone} required={!noPhone} disabled={noPhone} />
        <label className="nophone">
          <input type="checkbox" checked={noPhone}
                 onChange={(e) => setNoPhone(e.target.checked)} /> {T.noPhone}
        </label>
        <label className="dlab">{T.birth}
          <input type="date" value={birth} max={form.birth_max}
                 onChange={(e) => setBirth(e.target.value)} />
        </label>
        <button disabled={busy || !times.length}>{T.go}</button>
      </form>
    </dialog>
  )
}
