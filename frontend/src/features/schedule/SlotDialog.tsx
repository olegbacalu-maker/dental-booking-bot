import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { svcLabel, type NewAppt, type NewNote } from './day'
import { DurSelect, useDurPick } from './DurPick'
import { MinPick } from './MinPick'
import { freeRoom, laneOf, lanesOf, roomShared, type Occupies, type Room } from './move'
import { RoomSelect, sharedWarn } from './RoomPick'
import { hourMinutes, slotTimes, takenMinutes, type Slot, type SlotFormView } from './slot'
import { SmsCheck, useSmsBox } from './SmsBox'

/* Диалог свободной ячейки «+» (C25.5b): записать пациента ИЛИ заблокировать
   часы заметкой стойки. Разметка — те же классы, что печатает `_slot_modal`.

   ⚠️ Новая ячейка — чистый диалог: экран пересоздаёт его по ключу «врач|час»,
   поэтому сброс полей не нужен ни одним эффектом. Расхождение со старой
   страницей записано осознанно: там диалог ОДИН на весь документ, и набранное
   имя переживало закрытие — на другой ячейке оно подставлялось снова.
   ⭐ И это же держит набранное на ЖИВОМ экране (панель): состояние полей
   заводится при монтировании, а конверт приезжает каждые 12 секунд — пересевать
   их некому и незачем. Диалог визита добивается того же черновиком, потому что
   у него есть серверное значение, которое он показывает; здесь его нет.

   Минута двигает время ЗАПИСИ и заголовок, начало заметки остаётся часовым
   (`slotTimes`).
   ⚠️ Конец блокировки — голый час из `note_ends`, и только больше начала.
   Обеденный час оттуда выпал, поэтому закончить в 14:00 при обеде 13–14
   нельзя — это правило сервера, а не недосмотр списка.

   ⛔ Кнопка ЗАПЕРТА, пока команда в полёте (`busy`), и это не косметика:
   второй клик даёт честный отказ `dup`, но человек видел бы два ответа на одно
   действие. Ключа идемпотентности не нужно — нужна блокировка.
   ⛔ Диалог закрывается ТОЛЬКО на удаче. Отказ («интервал занят», «врач не
   работает в этот час») оставляет набранное на экране: закрыть форму, из
   которой ничего не записалось, значит потерять ввод и не сказать почему.
   ⛔ И отказ печатается ВНУТРИ окна (17.10): плашка экрана живёт на z-index
   80, а `<dialog>` — в top layer, и под открытым окном её не видно вовсе.
   Экран отдаёт слово отказа колбэком `fail`, а не плашкой.
   Занятость стартов — подсказка по канве с ВЫБРАННОЙ длительностью; занят
   весь час — кнопка выключена и сказано почему. Отказ сервера придёт `fail`.
   ⭐ «SMS reminder» рядом с «fără telefon» (Олег 19.10) — `SmsBox`, та же,
   что у `AddDialog`; видна по `form.sms`. */
const T = {
  appt: 'Programare',
  note: 'Notiță / blocare',
  service: 'Serviciu',
  name: 'Nume pacient',
  phone: 'Telefon',
  noPhone: 'fără telefon',
  birth: 'Data nașterii (opț.)',
  go: 'Adaugă programarea',
  text: 'ex.: pauză de masă, ședință, rezervat telefonic…',
  until: 'până la ora',
  goNote: 'Salvează notița (blochează orele)',
  close: 'Închide',
  noStart: (hh: string, dur: number) =>
    `Medicul nu are niciun început liber în ora ${hh}:00 pentru ${dur} min.`,
  noStartRoom: (hh: string, dur: number) =>
    `Cabinetul ales nu are niciun început liber în ora ${hh}:00 pentru ${dur} min.`,
  noFit: (at: string, dur: number) =>
    `De la ${at} nu încap ${dur} min până la următoarea programare — alegeți o durată mai scurtă sau alt început.`,
} as const

/** Слово отказа — колбэком в окно, не плашкой экрана. */
export type Fail = (text: string) => void

interface Props {
  open: boolean
  slot: Slot
  date: string
  form: SlotFormView
  noteEnds: number[]
  taken: Occupies[]
  rooms?: readonly Room[]
  others?: Occupies[]
  busy: boolean
  onClose: () => void
  onAdd: (body: NewAppt, fail: Fail) => Promise<boolean>
  onNote: (body: NewNote, fail: Fail) => Promise<boolean>
}

const NO_ROOMS: readonly Room[] = []
const NO_BLOCKS: Occupies[] = []

export function SlotDialog({ open, slot, date, form, noteEnds, taken, rooms = NO_ROOMS,
  others = NO_BLOCKS, busy, onClose, onAdd, onNote }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [tab, setTab] = useState<'a' | 'n'>('a')
  const [fail, setFail] = useState('')
  const [service, setService] = useState(form.services[0]?.id ?? '')
  const dur = useDurPick(form.services, service, form)
  const hh = slot.hour.split(':')[0] ?? ''
  const step = form.step ?? 5
  /* с длиной не по правилу считать нечего — меряем кратчайшим визитом */
  const span = dur.bad || !dur.value ? step : dur.value
  const many = rooms.length > 1
  /* кабинет выбран руками — занятость считается только по нему */
  const [roomPick, setRoomPick] = useState(many ? slot.room ?? '' : '')
  const scope = roomPick ? [laneOf(taken, roomPick)] : lanesOf(taken, rooms)
  const off = takenMinutes(scope, Number(hh), span, step)
  const firstFree = hourMinutes(step).find((m) => !off.has(m))
  const none = firstFree === undefined
  /* Минута щелчка держится, даже когда услуга по умолчанию в неё не влезает: окно
     говорит, что не влезло, а не уводит запись на другой конец часа. */
  const [aimed, setAimed] = useState(slot.minute !== undefined)
  const [minute, setMinute] = useState(slot.minute ?? firstFree ?? 0)
  const tight = aimed && off.has(minute)
  /* выбранный старт стал занят (новая канва, другая длительность) — на первый свободный */
  if (!aimed && !none && off.has(minute)) setMinute(firstFree)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')
  const sms = useSmsBox(form.sms, phone, noPhone)
  const [text, setText] = useState('')
  const [until, setUntil] = useState(0)

  const { atime, ntime, ends } = slotTimes(slot.hour, minute, noteEnds)
  const start = Number(hh) * 60 + minute
  const room = roomPick || freeRoom(taken, rooms, start, span, -1) || rooms[0]?.id || ''
  const shared = !none && !tight && roomShared(others, room, start, span)

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  async function submitAppt(e: FormEvent) {
    e.preventDefault()
    setFail('')
    const ok = await onAdd({ date, time: atime, doctor: slot.dk, service, name,
      phone: noPhone ? '' : phone, nophone: noPhone, birth, ...sms.field, ...dur.field,
      ...(roomPick ? { room: roomPick } : {}) }, setFail)
    if (ok) onClose()
  }

  async function submitNote(e: FormEvent) {
    e.preventDefault()
    setFail('')
    const ok = await onNote({ date, time: ntime, doctor: slot.dk, text,
      until: until || ends[0] || Number(hh) + 1 }, setFail)
    if (ok) onClose()
  }

  const pick = (m: number) => { setMinute(m); setAimed(false); setFail('') }
  const warn = fail || (tight ? T.noFit(atime, span)
    : none ? (roomPick ? T.noStartRoom : T.noStart)(hh, span) : '')
  const warnNode = warn ? <div className="banner err" role="alert">{warn}</div> : null

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{slot.name} — {atime}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <div className="dlg-tabs">
        <button type="button" className={`tabbtn${tab === 'a' ? ' on' : ''}`}
                onClick={() => setTab('a')}><Icon name="user" /> {T.appt}</button>
        <button type="button" className={`tabbtn${tab === 'n' ? ' on' : ''}`}
                onClick={() => setTab('n')}><Icon name="note" /> {T.note}</button>
      </div>
      {tab === 'a' ? (
        <form className="dlg-form" onSubmit={submitAppt}>
          <MinPick hh={hh} value={minute} step={step} taken={off} onPick={pick} />
          <div className="dp-addrow dp-svcrow">
            <select value={service} onChange={(e) => setService(e.target.value)}
                    aria-label={T.service}>
              {form.services.map((x) => <option key={x.id} value={x.id}>{svcLabel(x)}</option>)}
            </select>
            <DurSelect box={dur} />
          </div>
          {many ? <RoomSelect rooms={rooms} value={room}
                              onPick={(id) => { setRoomPick(id); setFail('') }} /> : null}
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
          {warnNode}
          {shared && !warn ? <div className="banner warn" role="status">{sharedWarn(rooms, room)}</div> : null}
          <button disabled={busy || none || tight || dur.bad}>{T.go}</button>
        </form>
      ) : (
        <form className="dlg-form" onSubmit={submitNote}>
          <input value={text} onChange={(e) => setText(e.target.value)}
                 placeholder={T.text} maxLength={120} required />
          <label className="dlab">{T.until}
            <select value={until || ends[0] || ''}
                    onChange={(e) => setUntil(Number(e.target.value))}>
              {ends.map((e) => <option key={e} value={e}>{e}:00</option>)}
            </select>
          </label>
          {fail ? <div className="banner err" role="alert">{fail}</div> : null}
          <button disabled={busy || !ends.length}>{T.goNote}</button>
        </form>
      )}
    </dialog>
  )
}
