import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { day, type DayForm, type NewAppt } from './day'
import { SmsCheck, useSmsBox } from './SmsBox'

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
   набранное на экране, как у окна свободного часа.

   ⛔ Часы — ДАТЫ ОКНА, а не дня экрана (19.10). `form` приезжает с днём
   экрана, а поле даты в окне редактируемое, и до 19.10 его смена список не
   трогала: шапка открывает окно на сегодня, в воскресенье (клиника закрыта)
   «Ora» пуст — и оставался пустым, когда регистратура ставила вторник. Другой
   день спрашивается ТЕМ ЖЕ построителем, что день экрана
   (`GET /api/schedule/day` › `form`): второго правила часов в браузере нет.
   ⚠️ Ответ принимается только для той даты, которую спрашивали, и только
   если сервер ответил ЕЮ: набор года по цифрам — четыре даты подряд, а
   кривую дату сервер молча читает как сегодня. Не пришло — список дня
   экрана, как до 19.10: запись всё равно проверит сервер.

   ⭐ «SMS reminder» рядом с «fără telefon» (Олег 19.10) — `SmsBox`; видна
   по `form.sms` дня ЭКРАНА: право и пакет от даты окна не зависят. */
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
  // та же фраза, что у канвы закрытого дня (`DashCanvas`)
  closed: 'Zi liberă — clinica este închisă',
} as const

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

interface Props {
  open: boolean
  form: DayForm
  /** День экрана: подставляется в поле даты при открытии. ⛔ Экран ставит окну
   *  `key` по дню — смена дня начинает запись заново, как перезагрузка старой
   *  страницы (Олег 24.09). */
  date: string
  /** Врач экрана (`''` — «Toți medicii»): форма другого дня спрашивается в
   *  том же составе, что день экрана. */
  of: string
  busy: boolean
  onClose: () => void
  /** `fail` — слово отказа В ОКНО (как у `SlotDialog`): плашка экрана под
   *  открытым `<dialog>` не видна (top layer). Так у обоих хозяев окна — дня
   *  журнала и окна шапки (`NewApptHost`). */
  onAdd: (body: NewAppt, fail: (text: string) => void) => Promise<boolean>
}

/** Форма записи на дату окна; `form: null` — не пришла. */
interface Got {
  at: string
  form: DayForm | null
}

export function AddDialog({ open, form, date, of, busy, onClose, onAdd }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [at, setAt] = useState(date)
  const [got, setGot] = useState<Got | null>(null)
  const [doctorPick, setDoctorPick] = useState('')
  const [timePick, setTimePick] = useState(form.time)
  const [service, setService] = useState(form.services[0]?.id ?? '')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')
  const [fail, setFail] = useState('')
  const sms = useSmsBox(form.sms, phone, noPhone)

  const other = at !== date && ISO_DAY.test(at)
  /* пока ответ в пути — последний пришедший список, а кнопка ждёт */
  const pending = other && got?.at !== at
  const f = (other && got?.form) || form
  /* список — именно этой даты (а не запасной): только тогда пустой список
     вправе сказать «клиника закрыта» */
  const sure = !other || (got?.at === at && got.form !== null)
  const doctor = f.times[doctorPick] ? doctorPick : f.doctor
  const times = f.times[doctor] ?? f.hours
  const time = times.includes(timePick) ? timePick : (times[0] ?? '')

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  useEffect(() => {
    if (!open || !other) return
    const ctl = new AbortController()
    day.get(at, of, '', ctl.signal).then(
      (r) => {
        if (!ctl.signal.aborted) {
          setGot({ at, form: r.data.date === at ? r.data.form : null })
        }
      },
      () => { if (!ctl.signal.aborted) setGot({ at, form: null }) },
    )
    return () => ctl.abort()
  }, [open, other, at, of])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setFail('')
    const ok = await onAdd({ date: at, time, doctor, service, name,
      phone: noPhone ? '' : phone, nophone: noPhone, birth, ...sms.field }, setFail)
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
        {/* пустой список значит одно: у клиники в этот день нет часов
            (`form_spec` подменяет пустое окно врача часами клиники) */}
        {sure && !times.length ? <p className="hint dp-m0">{T.closed}</p> : null}
        {f.doctors.length === 1
          ? <b className="dp-adddoc">{f.doctors[0]?.name}</b>
          : (
            <select value={doctor} onChange={(e) => setDoctorPick(e.target.value)}
                    aria-label={T.doctor}>
              {f.doctors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
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
        <div className="dp-addrow">
          <label className="nophone">
            <input type="checkbox" checked={noPhone}
                   onChange={(e) => setNoPhone(e.target.checked)} /> {T.noPhone}
          </label>
          <SmsCheck box={sms} />
        </div>
        <label className="dlab">{T.birth}
          <input type="date" value={birth} max={form.birth_max}
                 onChange={(e) => setBirth(e.target.value)} />
        </label>
        {fail ? <div className="banner err" role="alert">{fail}</div> : null}
        <button disabled={busy || pending || !times.length}>{T.go}</button>
      </form>
    </dialog>
  )
}
