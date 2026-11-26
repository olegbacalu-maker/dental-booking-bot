import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { HourSelect, MinPick } from './MinPick'
import { clashLanes, CONTROL, freeRoom, hhmm, laneOf, lanesOf, mainLanes, roomShared, sameSlot, type Drag, type Occupies,
  type Room, type Target } from './move'
import { AsControl, RoomSelect, sharedWarn } from './RoomPick'
import { takenMinutes } from './slot'
import { dayShort } from './when'

/* Подтверждение переноса (C25.5b). Диалог обязателен: перетащить мышью легко
   случайно, а визит — это человек, которому уже назвали время.

   ⚠️ Строка «De la» стоит здесь не для красоты: если блок уехал не туда,
   вернуть его можно, только зная, откуда он.
   ⚠️ Предупреждение о занятости — ПОДСКАЗКА. Правду говорит сервер под
   `_BOOK_LOCK`: пока тянули, час мог занять второй администратор.
   Имена колонок, блоки и часы колонки-цели даёт ЭКРАН готовыми: у дня и у
   панели разные модели. Точное время доводят здесь, врач — колонка броска.

   Окно одно на два входа. Бросок блока знает день и врача сам — их в окне нет.
   Кнопка «Mută» окна визита (`pick`) броска не имеет: день и врача выбирают
   здесь, а канву выбранного дня приносит хозяин (`Reschedule`). */
const T = {
  title: 'Mutare programare',
  who: 'Pacient',
  from: 'De la',
  to: 'La',
  no: 'Anulează',
  yes: 'Da, mută',
  close: 'Închide',
  date: 'Data',
  doctor: 'Medic',
  busyDoc: (at: string) => `Medicul are deja o programare la ${at}.`,
  busyRoom: (at: string) => `Cabinetul ales este ocupat de la ${at}.`,
  asControl: 'Mută în Control',
  // та же фраза, что у канвы закрытого дня (`DashCanvas`) и окна записи
  closed: 'Zi liberă — clinica este închisă',
  noHours: 'Medicul nu are program în ziua aleasă.',
  offHour: (at: string) => `Medicul nu are program la ora ${at}.`,
  past: 'Atenție: data aleasă este în trecut.',
} as const

/* Самое длинное из слов самого окна: невидимая плашка с ним держит место под слово —
   в одну строку на широком окне, в две на телефоне, как настоящая. */
const SAY_ROOM = [T.busyDoc('00:00'), T.busyRoom('00:00'), T.closed, T.noHours, T.offHour('00:00'), T.past]
  .reduce((a, b) => (b.length > a.length ? b : a))

const NO_ROOMS: readonly Room[] = []
const NO_BLOCKS: Occupies[] = []

/** День и врач, которые выбирают в окне (вход из окна визита). */
export interface MovePick {
  /** День окна и день, на котором запись стоит сейчас. */
  date: string
  from: string
  /** «Сегодня» клиники — его даёт сервер; пусто — о прошедшем дне окно молчит. */
  today: string
  doctors: readonly { id: string; name: string }[]
  /** Канвы дня окна нет: подсказки молчат, кнопка ждёт. */
  pending: boolean
  /** В выбранный день у клиники нет часов вовсе. */
  closed: boolean
  /** Отказ сервера — его словами, в окне: плашка экрана под окном не видна. */
  fail: string
  onDate: (iso: string) => void
  onDoctor: (dk: string) => void
  /** Выбрали другой час, минуту или кабинет: слово прежнего отказа больше не про это место. */
  onPlace: () => void
}

interface Props {
  open: boolean
  drag: Drag
  /** `dk` читается на каждом рендере (в окне визита врача меняют), `min` и
   *  `room` — начальные значения полей. */
  target: Target
  /** Имя колонки, ИЗ которой тащат, и той, КУДА. */
  fromName: string
  toName: string
  taken: Occupies[]
  rooms?: readonly Room[]
  others?: Occupies[]
  /** Рабочие часы врача-цели («HH:00»); час броска есть в списке всегда. */
  hours: string[]
  step?: number | undefined
  busy: boolean
  pick?: MovePick | undefined
  onClose: () => void
  /** Минута от полуночи и кабинет, если его выбрали; без него кабинет ставит сервер. */
  onMove: (min: number, room?: string) => void
}

export function MoveDialog({ open, drag, target, fromName, toName, taken, rooms = NO_ROOMS,
  others = NO_BLOCKS, hours, step = 5, busy, pick, onClose, onMove }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const dropped = `${String(Math.floor(target.min / 60)).padStart(2, '0')}:00`
  const [hourPick, setHourPick] = useState(dropped)
  const [minute, setMinute] = useState(target.min % 60)
  /* у броска в списке всегда его час; у окна с датой — выбранный: в другой
     день его может не быть, и это говорится словом, а час сам не меняется */
  const shownHour = pick ? hourPick : dropped
  const list = hours.includes(shownHour) ? hours : [shownHour, ...hours].sort()
  const hh = hourPick.split(':')[0] ?? ''
  const hour = Number(hh)
  const min = hour * 60 + minute
  const many = rooms.length > 1
  const [roomChoice, setRoomChoice] = useState(target.room ?? '')
  /* выбор держится, пока он есть у врача: другой врач — снова как решит сервер */
  const roomPick = many && rooms.some((r) => r.id === roomChoice) ? roomChoice : ''
  const scope = roomPick ? [laneOf(taken, roomPick)] : lanesOf(taken, mainLanes(rooms))
  const off = takenMinutes(scope, hour, drag.dur, step, drag.id)
  const busyAt = clashLanes(scope, min, drag.dur, drag.id)
  /* без выбора — как решит сервер: у того же врача запись остаётся в своём
     кабинете, пока он свободен, иначе первый свободный */
  const own = target.dk === drag.dk && drag.room && rooms.some((r) => r.id === drag.room)
    && clashLanes([laneOf(taken, drag.room)], min, drag.dur, drag.id) < 0 ? drag.room : ''
  const room = roomPick || (own === CONTROL ? '' : own) || freeRoom(taken, mainLanes(rooms), min, drag.dur, drag.id)
    || rooms[0]?.id || ''
  const shared = busyAt < 0
    && roomShared(others.filter((it) => it.id !== drag.id), room, min, drag.dur)
  const nameOf = (id?: string) => {
    const name = rooms.find((r) => r.id === id)?.name
    return name ? ` · ${name}` : ''
  }
  /* основная занята, а полоса Control врача-цели свободна — выход явным нажатием */
  const ctlFree = busyAt >= 0 && roomPick !== CONTROL && rooms.some((r) => r.control)
    && clashLanes([laneOf(taken, CONTROL)], min, drag.dur, drag.id) < 0
  const otherDay = !!pick && pick.date !== pick.from
  /* своё же место: сервер такой перенос принял бы и записал в летопись */
  const same = !otherDay && sameSlot(drag, { dk: target.dk, min, ...(many ? { room } : {}) })
  /* часы дня известны, а выбранного среди них нет — сервер ответил бы отказом */
  const noHour = !!pick && !pick.pending && !hours.includes(hourPick)
  const wait = !!pick && (pick.pending || noHour)
  /* граница дневная, как у предупреждения сервера: прошедший час сегодня — обычная работа */
  const past = otherDay && !!pick.today && pick.date < pick.today
  const pickHour = (h: string) => { setHourPick(h); pick?.onPlace() }
  const pickMinute = (m: number) => { setMinute(m); pick?.onPlace() }
  const pickRoom = (id: string) => { setRoomChoice(id); pick?.onPlace() }
  const dayOf = (iso: string) => {
    const day = dayShort(iso)
    return day ? ` · ${day}` : ''
  }
  /* что окно говорит, по важности: сперва то, что запирает кнопку */
  const says: { tone: 'err' | 'warn'; text: string }[] = []
  if (pick?.fail) says.push({ tone: 'err', text: pick.fail })
  if (noHour) says.push({ tone: 'err', text: pick?.closed ? T.closed : hours.length ? T.offHour(hhmm(hour * 60)) : T.noHours })
  else if (busyAt >= 0) says.push({ tone: 'err', text: (roomPick ? T.busyRoom : T.busyDoc)(hhmm(busyAt)) })
  if (past) says.push({ tone: 'warn', text: T.past })
  if (shared) says.push({ tone: 'warn', text: sharedWarn(rooms, room) })
  const say = (m: { tone: 'err' | 'warn'; text: string }) => (
    <div key={m.text} className={`banner ${m.tone}`} role={m.tone === 'err' ? 'alert' : 'status'}>{m.text}</div>
  )

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])


  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <div className="dlg-form" aria-busy={pick?.pending || undefined}>
        <div className="mv-rows">
          <div><span>{T.who}</span><b>{drag.nm}</b></div>
          <div><span>{T.from}</span><b>{fromName}{pick ? dayOf(pick.from) : ''} · {hhmm(drag.min)}{many ? nameOf(drag.room) : ''}</b></div>
          <div><span>{T.to}</span><b>{toName}{pick ? dayOf(pick.date) : ''} · {hhmm(min)}{many ? nameOf(room) : ''}</b></div>
        </div>
        {pick ? (
          <div className="dp-addrow">
            <label className="dlab">{T.date}
              <input type="date" value={pick.date} required onChange={(e) => pick.onDate(e.target.value)} />
            </label>
            <HourSelect hours={list} value={hourPick} onPick={pickHour} />
          </div>
        ) : <HourSelect hours={list} value={hourPick} onPick={pickHour} />}
        <MinPick hh={hh} value={minute} step={step} taken={off} onPick={pickMinute} />
        {/* список врачей приходит с канвой дня: поле стоит с первого кадра, чтобы окно не росло */}
        {pick ? (
          <select value={target.dk} aria-label={T.doctor} disabled={pick.doctors.length < 2}
                  onChange={(e) => pick.onDoctor(e.target.value)}>
            {pick.doctors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        ) : null}
        {many ? <RoomSelect rooms={rooms} value={room} onPick={pickRoom} /> : null}
        {/* день и час здесь меняют по многу раз: место под слово занято всегда, слово одно —
            самое важное; у броска слова стоят как стояли */}
        {pick ? (
          <div className="mv-say">
            <div className="banner mv-say-room" aria-hidden="true">{SAY_ROOM}</div>
            {says[0] ? say(says[0]) : null}
          </div>
        ) : says.map(say)}
        {ctlFree && !wait ? <AsControl label={T.asControl} disabled={busy} onClick={() => onMove(min, CONTROL)} /> : null}
        <div className="mv-act">
          <button type="button" className="mv-no" onClick={onClose}>{T.no}</button>
          <button type="button" onClick={() => onMove(min, roomPick || undefined)}
                  disabled={busy || busyAt >= 0 || same || wait}>
            {T.yes}
          </button>
        </div>
      </div>
    </dialog>
  )
}
