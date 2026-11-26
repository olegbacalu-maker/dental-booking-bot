import { useEffect, useState } from 'react'
import { canvasBlocks, canvasColName, canvasOpenHours, canvasOthers, canvasRooms, type DashCanvasModel } from './dash'
import { day, type DayModel } from './day'
import { MoveDialog } from './MoveDialog'
import { CONTROL, hhmm, type Drag } from './move'

/* «Mută» окна визита: то же окно переноса, но день и врача выбирают в нём.

   Канва выбранного дня спрашивается тем же `GET /api/schedule/day`, что день
   экрана: занятые минуты, открытые часы врача и его кабинеты — из неё, второго
   правила часов в браузере нет. Спрашивается общий день (без врача): на дне
   одного врача перенос к другому иначе был бы вслепую; учётке врача сервер
   сам отдаёт только её колонку.
   Ответ принимается только для спрошенной даты и только если сервер ответил
   ею: кривую дату он молча читает как сегодня.
   Первый кадр рисуется по канве экрана — окно открывается без ожидания и не
   перестраивается, когда приходит ответ. */
const T = {
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

export interface MoveBody {
  date: string
  time: string
  doctor: string
  room?: string
}

interface Props {
  open: boolean
  /** Запись, как её сняло бы перетаскивание (`dash.canvasDrag`). */
  drag: Drag
  /** Канва дня экрана: на ней запись стоит сейчас. */
  canvas: DashCanvasModel
  step?: number | undefined
  /** «Сегодня» клиники из формы экрана. */
  today: string
  busy: boolean
  onClose: () => void
  /** `true` — перенесено, окно закрывается; отказ приходит словом в `fail`. */
  onMove: (body: MoveBody, fail: (text: string) => void) => Promise<boolean>
}

/** День окна, каким его отдал сервер; `model: null` — не пришёл. */
interface Got {
  at: string
  model: DayModel | null
}

export function Reschedule({ open, drag, canvas, step, today, busy, onClose, onMove }: Props) {
  const [at, setAt] = useState(canvas.date)
  const [dk, setDk] = useState(drag.dk)
  const [got, setGot] = useState<Got | null>(null)
  const [fail, setFail] = useState('')
  /* врачи и кабинеты от дня не зависят: последние известные держат окно в
     одном виде, пока канва нового дня в пути */
  const [known, setKnown] = useState<DayModel | null>(null)
  const valid = ISO_DAY.test(at)

  useEffect(() => {
    if (!open || !valid) return
    const ctl = new AbortController()
    day.get(at, '', '', ctl.signal).then(
      (r) => {
        if (ctl.signal.aborted) return
        const model = r.data.date === at ? r.data : null
        setGot({ at, model })
        if (model) setKnown(model)
      },
      () => { if (!ctl.signal.aborted) setGot({ at, model: null }) },
    )
    return () => ctl.abort()
  }, [open, valid, at])

  const mine = got?.at === at ? got : null
  const cv = mine?.model?.canvas ?? (at === canvas.date ? canvas : null)
  const last = known?.canvas ?? canvas
  const active = known?.form?.doctors ?? []
  /* врач записи есть в списке всегда: выключенного в форме нет, а запись от него уводят */
  const doctors = active.some((x) => x.id === drag.dk)
    ? active : [{ id: drag.dk, name: canvasColName(canvas, drag.dk) }, ...active]
  const rooms = canvasRooms(cv, dk)
  const lost = valid && mine !== null && cv === null

  return (
    <MoveDialog open={open} drag={drag} busy={busy} step={step}
      target={{ dk, min: drag.min, ...(drag.room === CONTROL ? { room: CONTROL } : {}) }}
      fromName={canvasColName(canvas, drag.dk)}
      toName={doctors.find((x) => x.id === dk)?.name ?? canvasColName(last, dk)}
      taken={canvasBlocks(cv, dk)} hours={canvasOpenHours(cv, dk)}
      rooms={rooms.length ? rooms : canvasRooms(last, dk)}
      others={canvasOthers(cv, dk)}
      pick={{
        date: at, from: canvas.date, today, doctors,
        pending: cv === null, closed: cv?.empty === true,
        fail: fail || (lost ? T.offline : ''),
        onDate: (iso) => { setAt(iso); setFail('') },
        onDoctor: (id) => { setDk(id); setFail('') },
      }}
      onClose={onClose}
      onMove={(min, room) => {
        setFail('')
        void onMove({ date: at, time: hhmm(min), doctor: dk, ...(room ? { room } : {}) }, setFail)
          .then((ok) => { if (ok) onClose() })
      }} />
  )
}
