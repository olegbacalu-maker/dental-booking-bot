import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { day, svcLabel, type DayForm, type NewAppt } from './day'
import { DurSelect, useDurPick } from './DurPick'
import { HourSelect, MinPick } from './MinPick'
import { AsControl, RoomSelect } from './RoomPick'
import { busyInfo, CONTROL, CONTROL_DUR, type BusyInfo } from './move'
import { PatientName, PhoneHit, personRow, usePatientPick } from './PatientPick'
import { SmsCheck, useSmsBox } from './SmsBox'
import { whenLine } from './when'

/* «Programare nouă» окном (06.10, Олег: форма внизу страницы — старый облик,
   на панели новая запись открывается окном). Ручная запись по телефону и у
   стойки — то же, что делала нижняя форма журнала (C25.5b), и те же правила.

   ⛔ Врачи и часы — ИЗ `form`, а не из колонок канвы. На канве остаётся
   колонка выключенного врача, пока у него есть записи дня, а запись ответит
   ему `bad_off`: возьми список из колонок — регистратура выбрала бы такого
   врача и получила отказ на ровном месте.
   Смена врача переписывает список часов и сохраняет выбранный час, если он
   есть и у нового. Список часов один на все услуги: поздний старт длинной
   услуги отобьётся кодом `outside`. Занятость минут не подсказывается —
   канвы даты окна у окна нет.
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
  doctor: 'Medic',
  service: 'Serviciu',
  noPhone: 'fără telefon',
  birth: 'Data nașterii (opț.)',
  go: 'Adaugă programarea',
  phone: 'Telefon',
  close: 'Închide',
  // та же фраза, что у канвы закрытого дня (`DashCanvas`)
  closed: 'Zi liberă — clinica este închisă',
  // визит с бумаги (29.10, «Rechemări», В3 = А; кадр К8): дата в прошлом
  pastWarn: 'Data este în trecut.',
  happened: 'Vizita a avut loc — intră direct ca finalizată',
  happenedHint: 'Pentru istoricul de pe hârtie: vizita contează pentru Rechemări de la această dată.',
  pickDoctor: 'Alegeți medicul…',
  people: 'Fișă existentă:',
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
  onAdd: (body: NewAppt & { pid?: number }, fail: (text: string, code?: string, data?: unknown) => void) => Promise<boolean>
  preset?: AddPreset | undefined
  /** Строка над формой: откуда запись (событие календаря) — только текстом. */
  note?: string | undefined
  /** Фиши, похожие на пациента записи: выбранная получает запись по номеру
   *  фиши, имя и телефон окна тогда не читаются. */
  people?: AddPerson[] | undefined
  /** Врача выбирает человек: без `preset.doctor` окно не ставит первого молча. */
  askDoctor?: boolean | undefined
  /** Фиша экрана под окном (окно шапки поверх фиши): первая строка «Recenți», не подстановка. */
  here?: number | undefined
}

export interface AddPerson { id: number; name: string; phone: string }

export interface AddPreset {
  date?: string
  time?: string
  duration?: number
  doctor?: string
  service?: string
  name?: string
  phone?: string
  room?: string
  pid?: number
}

/** Форма записи на дату окна; `form: null` — не пришла. */
interface Got {
  at: string
  form: DayForm | null
}

export function AddDialog({
  open, form, date, of, busy, onClose, onAdd, preset, note, people, askDoctor, here,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [at, setAt] = useState(preset?.date ?? date)
  const seedTime = preset?.time ?? form.time
  const [got, setGot] = useState<Got | null>(null)
  const [doctorPick, setDoctorPick] = useState(preset?.doctor ?? '')
  const [timePick, setTimePick] = useState(seedTime ? `${seedTime.split(':')[0]}:00` : '')
  const [minute, setMinute] = useState(Number(seedTime.split(':')[1] ?? 0) || 0)
  const [roomPick, setRoomPick] = useState(preset?.room ?? '')
  const [service, setService] = useState(
    form.services.find((x) => x.id === preset?.service)?.id ?? form.services[0]?.id ?? '')
  const [phone, setPhone] = useState(preset?.phone ?? '')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')
  const [fail, setFail] = useState('')
  const [failCode, setFailCode] = useState('')
  const [busyAt, setBusyAt] = useState<BusyInfo | null>(null)
  const seed = people?.find((x) => x.id === preset?.pid)
  const pick = usePatientPick(phone, noPhone, seed ? personRow(seed) : null, preset?.name ?? '')
  const person = pick.picked
  const pid = person?.id ?? null
  const sms = useSmsBox(form.sms, person ? person.phone : phone, person ? !person.phone : noPhone)
  const dur = useDurPick(form.services, service, form,
    preset?.duration ?? (preset?.room === CONTROL ? CONTROL_DUR : undefined))
  /* «Сегодня» — `birth_max` формы (день клиники, его дал сервер), не часы
     браузера. Галочка включена сразу (решение Олега 29.10): визит задним
     числом заводят ради бумажной истории, а забытая галочка оставила бы его
     «programată», и часы отзыва не пошли бы. Правду всё равно говорит
     сервер: на день не в прошлом поле игнорируется. */
  const past = ISO_DAY.test(at) && at < form.birth_max
  const [happened, setHappened] = useState(true)

  const other = at !== date && ISO_DAY.test(at)
  /* пока ответ в пути — последний пришедший список, а кнопка ждёт */
  const pending = other && got?.at !== at
  const f = (other && got?.form) || form
  /* список — именно этой даты (а не запасной): только тогда пустой список
     вправе сказать «клиника закрыта» */
  const sure = !other || (got?.at === at && got.form !== null)
  const doctor = f.times[doctorPick] ? doctorPick : f.doctor
  const noDoctor = !!askDoctor && f.doctors.length > 1 && !f.times[doctorPick]
  const times = f.times[doctor] ?? f.hours
  const hour = times.includes(timePick) ? timePick : (times[0] ?? '')
  const hh = hour.split(':')[0] ?? ''
  const time = hour ? `${hh}:${String(minute).padStart(2, '0')}` : ''
  const rooms = f.doctors.find((x) => x.id === doctor)?.rooms ?? []
  const parallel = !!f.doctors.find((x) => x.id === doctor)?.parallel
  /* выбор держится, пока он есть у врача: другой врач — снова «первый свободный» */
  const room = rooms.length > 1 && rooms.some((r) => r.id === roomPick) ? roomPick : ''

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

  async function submit(e: FormEvent | null, asControl = false) {
    e?.preventDefault()
    setFail('')
    setFailCode('')
    const who = person
      ? { name: person.name, phone: person.phone, nophone: !person.phone, pid: person.id }
      : { name: pick.name, phone: noPhone ? '' : phone, nophone: noPhone }
    const lane = asControl ? CONTROL : room
    /* «ca control» с нетронутой длительностью — короткая, как в полосе */
    const durField = asControl && !dur.field.duration ? { duration: CONTROL_DUR } : dur.field
    const ok = await onAdd({ date: at, time, doctor, service, ...who, birth, ...sms.field,
      ...durField, ...(lane ? { room: lane } : {}), ...(past ? { done: happened } : {}) },
    (text, code, data) => { setFail(text); setFailCode(code ?? ''); setBusyAt(busyInfo(data)) })
    if (ok) onClose()
  }

  /* «Alege HH:MM»: ближайшее свободное время основной колонки — в поля часа и минуты */
  const pickNext = (t: string) => {
    const [h, m] = t.split(':')
    setTimePick(`${h}:00`)
    setMinute(Number(m) || 0)
    setFail('')
    setFailCode('')
    setBusyAt(null)
  }

  const pickRoom = (id: string) => {
    setRoomPick(id)
    setFail('')
    setFailCode('')
    if (id === CONTROL && !dur.field.duration) dur.pick(CONTROL_DUR)
  }

  return (
    <dialog ref={ref} onClose={onClose} className="dp-adddlg">
      <div className="dlg-head">
        <span><Icon name="plus" /> {T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <p className="dp-when" data-empty={hour ? undefined : ''}>
        <Icon name="clock" /> <span>{whenLine(at, hour, minute, dur.bad ? 0 : dur.value)}</span>
      </p>
      <form className="dlg-form dp-addform" onSubmit={submit}>
        {note ? <p className="hint dp-m0 dp-addnote">{note}</p> : null}
        <div className="dp-addrow">
          <label className="dlab">{T.date}
            <input type="date" value={at} onChange={(e) => setAt(e.target.value)} required />
          </label>
          <HourSelect hours={times} value={hour} onPick={setTimePick} />
        </div>
        {times.length
          ? <MinPick hh={hh} value={minute} step={f.step ?? 5} onPick={setMinute} />
          : null}
        {/* пустой список значит одно: у клиники в этот день нет часов
            (`form_spec` подменяет пустое окно врача часами клиники) */}
        {sure && !times.length ? <p className="hint dp-m0">{T.closed}</p> : null}
        {f.doctors.length === 1
          ? <b className="dp-adddoc">{f.doctors[0]?.name}</b>
          : (
            <select value={noDoctor ? '' : doctor} onChange={(e) => setDoctorPick(e.target.value)}
                    aria-label={T.doctor} required={noDoctor}>
              {noDoctor ? <option value="">{T.pickDoctor}</option> : null}
              {f.doctors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          )}
        <div className="dp-addrow dp-svcrow">
          <select value={service} onChange={(e) => setService(e.target.value)}
                  aria-label={T.service}>
            {form.services.map((x) => <option key={x.id} value={x.id}>{svcLabel(x)}</option>)}
          </select>
          <DurSelect box={dur} />
        </div>
        {rooms.length > 1
          ? <RoomSelect rooms={rooms} value={room} onPick={pickRoom} auto /> : null}
        {people?.length ? (
          <div className="dp-addpeople">
            <span className="hint">{T.people}</span>
            {people.map((x) => (
              <button key={x.id} type="button" className={`dp-addperson${pid === x.id ? ' on' : ''}`}
                      aria-pressed={pid === x.id} onClick={() => pick.setPicked(pid === x.id ? null : personRow(x))}>
                {x.name}{x.phone ? ` · ${x.phone}` : ''}
              </button>
            ))}
          </div>
        ) : null}
        <PatientName pick={pick} here={here} required onPhone={(p) => { if (!phone) setPhone(p) }} />
        <span className={`dp-pick${pick.phoneHit && !person ? ' has-pill' : ''}`}>
          <input value={person ? person.phone : noPhone ? '' : phone}
                 onChange={(e) => setPhone(e.target.value)} aria-label={T.phone}
                 placeholder={T.phone} required={!noPhone && !person} disabled={noPhone || !!person} />
          <PhoneHit pick={pick} />
        </span>
        <div className="dp-addrow">
          <label className="nophone">
            <input type="checkbox" checked={noPhone} disabled={!!person}
                   onChange={(e) => setNoPhone(e.target.checked)} /> {T.noPhone}
          </label>
          <SmsCheck box={sms} />
        </div>
        {/* дата рождения уже в выбранной фише: поле прячется, но место держит — окно не прыгает */}
        <label className={`dlab${person ? ' dp-pick-off' : ''}`} aria-hidden={person ? true : undefined}>{T.birth}
          <input type="date" value={birth} max={form.birth_max}
                 onChange={(e) => setBirth(e.target.value)} />
        </label>
        {past && (
          <div className="dp-past">
            <span className="dp-past-w"><Icon name="clock" /> {T.pastWarn}</span>
            <label className="nophone">
              <input type="checkbox" checked={happened} onChange={(e) => setHappened(e.target.checked)} /> <b>{T.happened}</b>
            </label>
            <small className="hint">{T.happenedHint}</small>
          </div>
        )}
        {fail ? <div className="banner err" role="alert">{fail}</div> : null}
        {/* отказ «врач занят» у врача с Control — та же запись в полосу, явным нажатием */}
        {fail && failCode === 'conflict' && parallel && room !== CONTROL
          ? <AsControl disabled={busy} onClick={() => { void submit(null, true) }}
              next={busyAt?.next ?? null} onNext={pickNext} /> : null}
        <button disabled={busy || pending || !times.length || dur.bad || noDoctor}>{T.go}</button>
      </form>
    </dialog>
  )
}
