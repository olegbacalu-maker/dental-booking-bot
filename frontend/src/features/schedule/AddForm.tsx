import { useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import type { DayForm, NewAppt } from './day'

/* Нижняя форма журнала: ручная запись по телефону и у стойки (C25.5b).

   ⛔ Врачи и часы — ИЗ `form`, а не из колонок сетки. В сетке остаётся
   колонка выключенного врача, пока у него есть записи дня, а `/admin/add`
   ответит ему `bad_off`: возьми список из колонок — регистратура выбрала бы
   такого врача и получила отказ на ровном месте.
   ⚠️ Смена врача переписывает список часов и СОХРАНЯЕТ выбранный час, если
   он есть и у нового, — ровно как DOC_TIMES на старой странице.
   ⚠️ Список часов один на все услуги (сервер считает его на 30 минут): у
   часовой услуги поздний старт отобьётся кодом `outside`, и это та же
   подсказка, что была. */
const T = {
  title: 'Adaugă programare manual (telefon / recepție)',
  noPhone: 'fără telefon',
  birth: 'Naștere (opț.)',
  go: 'Adaugă',
  name: 'Nume pacient',
  phone: 'Telefon',
} as const

interface Props {
  form: DayForm
  /** День экрана: он же подставляется в поле даты — ОДИН раз, при монтировании.
   *  ⛔ Поэтому экран ставит форме `key` по дню (DayScreen). */
  date: string
  busy: boolean
  onAdd: (body: NewAppt) => Promise<boolean>
}

export function AddForm({ form, date, busy, onAdd }: Props) {
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

  async function submit(e: FormEvent) {
    e.preventDefault()
    const ok = await onAdd({ date: at, time, doctor, service, name,
      phone: noPhone ? '' : phone, nophone: noPhone, birth })
    if (ok) {
      setName('')
      setPhone('')
      setNoPhone(false)
      setBirth('')
    }
  }

  return (
    <>
      <h2 id="addform"><Icon name="pen" /> {T.title}</h2>
      <form className="add" onSubmit={submit}>
        <input type="date" value={at} onChange={(e) => setAt(e.target.value)} required />
        <select value={time} onChange={(e) => setTimePick(e.target.value)}
                aria-label="Ora">
          {times.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {form.doctors.length === 1
          ? <b>{form.doctors[0]?.name}</b>
          : (
            <select value={doctor} onChange={(e) => setDoctorPick(e.target.value)}
                    aria-label="Medic">
              {form.doctors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          )}
        <select value={service} onChange={(e) => setService(e.target.value)}
                aria-label="Serviciu">
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
        <label className="dp-birth">{T.birth}
          <input type="date" value={birth} max={form.birth_max}
                 onChange={(e) => setBirth(e.target.value)} />
        </label>
        <button disabled={busy || !times.length}>{T.go}</button>
      </form>
    </>
  )
}
