import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { HourSelect, MinPick } from './MinPick'
import { clashLanes, freeRoom, hhmm, laneOf, lanesOf, roomShared, sameSlot, type Drag, type Occupies,
  type Room, type Target } from './move'
import { RoomSelect, sharedWarn } from './RoomPick'
import { takenMinutes } from './slot'

/* Подтверждение переноса (C25.5b). Диалог обязателен: перетащить мышью легко
   случайно, а визит — это человек, которому уже назвали время.

   ⚠️ Строка «De la» стоит здесь не для красоты: если блок уехал не туда,
   вернуть его можно, только зная, откуда он.
   ⚠️ Предупреждение о занятости — ПОДСКАЗКА. Правду говорит сервер под
   `_BOOK_LOCK`: пока тянули, час мог занять второй администратор.
   Имена колонок, блоки и часы колонки-цели даёт ЭКРАН готовыми: у дня и у
   панели разные модели, а диалог переноса один на оба.
   Бросок даёт час и половину; точное время доводят здесь, врач остаётся тем,
   в чью колонку бросили. */
const T = {
  title: 'Mutare programare',
  who: 'Pacient',
  from: 'De la',
  to: 'La',
  no: 'Anulează',
  yes: 'Da, mută',
  close: 'Închide',
  busyDoc: (at: string) => `Medicul are deja o programare la ${at}.`,
  busyRoom: (at: string) => `Cabinetul ales este ocupat de la ${at}.`,
} as const

const NO_ROOMS: readonly Room[] = []
const NO_BLOCKS: Occupies[] = []

interface Props {
  open: boolean
  drag: Drag
  target: Target
  /** Имя колонки, ИЗ которой тащат, и той, КУДА. */
  fromName: string
  toName: string
  /** Занятые блоки колонки-цели по канве — подсказка, а не запрет сервера. */
  taken: Occupies[]
  /** Кабинеты врача-цели по порядку; меньше двух — выбора в окне нет. */
  rooms?: readonly Room[]
  /** Блоки остальных колонок: по ним окно предупреждает о занятом кабинете. */
  others?: Occupies[]
  /** Рабочие часы врача-цели («HH:00»); час броска есть в списке всегда. */
  hours: string[]
  /** Шаг сетки стартов, минут. */
  step?: number | undefined
  busy: boolean
  onClose: () => void
  /** Минута от полуночи, выбранная в окне, и кабинет, если его выбрали руками
   *  или дорожкой броска; без него кабинет ставит сервер. */
  onMove: (min: number, room?: string) => void
}

export function MoveDialog({ open, drag, target, fromName, toName, taken, rooms = NO_ROOMS,
  others = NO_BLOCKS, hours, step = 5, busy, onClose, onMove }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const dropped = `${String(Math.floor(target.min / 60)).padStart(2, '0')}:00`
  const [hourPick, setHourPick] = useState(dropped)
  const [minute, setMinute] = useState(target.min % 60)
  const list = hours.includes(dropped) ? hours : [dropped, ...hours].sort()
  const hh = hourPick.split(':')[0] ?? ''
  const hour = Number(hh)
  const min = hour * 60 + minute
  const many = rooms.length > 1
  const [roomPick, setRoomPick] = useState(many ? target.room ?? '' : '')
  const scope = roomPick ? [laneOf(taken, roomPick)] : lanesOf(taken, rooms)
  const off = takenMinutes(scope, hour, drag.dur, step, drag.id)
  const busyAt = clashLanes(scope, min, drag.dur, drag.id)
  /* без выбора — как решит сервер: у того же врача запись остаётся в своём
     кабинете, пока он свободен, иначе первый свободный */
  const own = target.dk === drag.dk && drag.room && rooms.some((r) => r.id === drag.room)
    && clashLanes([laneOf(taken, drag.room)], min, drag.dur, drag.id) < 0 ? drag.room : ''
  const room = roomPick || own || freeRoom(taken, rooms, min, drag.dur, drag.id)
    || rooms[0]?.id || ''
  const shared = busyAt < 0
    && roomShared(others.filter((it) => it.id !== drag.id), room, min, drag.dur)
  const nameOf = (id?: string) => {
    const name = rooms.find((r) => r.id === id)?.name
    return name ? ` · ${name}` : ''
  }
  /* своё же место: сервер такой перенос принял бы и записал в летопись */
  const same = sameSlot(drag, { dk: target.dk, min, ...(many ? { room } : {}) })

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
      <div className="dlg-form">
        <div className="mv-rows">
          <div><span>{T.who}</span><b>{drag.nm}</b></div>
          <div><span>{T.from}</span><b>{fromName} · {hhmm(drag.min)}{many ? nameOf(drag.room) : ''}</b></div>
          <div><span>{T.to}</span><b>{toName} · {hhmm(min)}{many ? nameOf(room) : ''}</b></div>
        </div>
        <HourSelect hours={list} value={hourPick} onPick={setHourPick} />
        <MinPick hh={hh} value={minute} step={step} taken={off} onPick={setMinute} />
        {many ? <RoomSelect rooms={rooms} value={room} onPick={setRoomPick} /> : null}
        {busyAt >= 0 ? (
          <div className="banner err" role="alert">
            {(roomPick ? T.busyRoom : T.busyDoc)(hhmm(busyAt))}
          </div>
        ) : null}
        {shared ? <div className="banner warn" role="status">{sharedWarn(rooms, room)}</div> : null}
        <div className="mv-act">
          <button type="button" className="mv-no" onClick={onClose}>{T.no}</button>
          <button type="button" onClick={() => onMove(min, roomPick || undefined)} disabled={busy || busyAt >= 0 || same}>
            {T.yes}
          </button>
        </div>
      </div>
    </dialog>
  )
}
