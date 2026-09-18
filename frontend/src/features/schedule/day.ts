import { api } from '../../services/api'

/* Сетка дня (C25). Формы ответа — bot/app/modules/schedule/api.py и day.py:
   состав колонок, диапазон часов, исход ячейки и цвет считает СЕРВЕР.

   ⛔ Колонки — СПИСОК, и ячейка ссылается на позицию в нём. Врачей бывает
   ноль, один (день врача) или все, а выключенный остаётся колонкой, пока у
   него есть записи: раскладка по фиксированным местам сломалась бы на первом
   же таком дне.
   ⛔ Поля перетаскивания (`min`, `dur`, `busy`, `movable`) — тот же договор,
   что у `_move_attrs` старой страницы. Разойдись они, перенос молча перестал
   бы работать, а поймать это можно только руками. */

export type CellKind = 'appts' | 'busy' | 'off' | 'free'

export interface DayAppt {
  kind: 'appt'
  id: number
  time: string
  name: string
  service: string
  phone: string
  status: string
  /** Слово статуса — сервера; второго словаря в клиенте нет. */
  status_label: string
  urgent: boolean
  source: string
  dur: number
  comment: string
  /** Возраст считает сервер той же функцией, что печатает карточку. */
  age: number | null
  clickable: boolean
  /** Переменные темы для фона и полосы. */
  bg: string
  bar: string
  /** Минуты от полуночи — для переноса. */
  min: number
  /** Визит занимает интервал (те же статусы, что считает сервер). */
  busy: boolean
  movable: boolean
}

export interface DayNote {
  kind: 'note'
  id: number
  time: string
  text: string
  min: number
  dur: number
  busy: boolean
  movable: boolean
}

export type DayItem = DayAppt | DayNote

export interface DayCell {
  kind: CellKind
  /** Приёмный час врача: мишень переноса, занят он или нет. */
  drop: boolean
  items: DayItem[]
}

export interface DayHour {
  h: number
  label: string
  /** «» — рабочий час, «pauza» — обед клиники, «inchis» — вне графика. */
  closed: '' | 'pauza' | 'inchis'
  now: boolean
  cells: DayCell[]
}

export interface DayColumn {
  id: string
  name: string
  /** Специальность; у выключенного врача сюда дописано «· inactiv». */
  spec: string
}

export interface DayModel {
  date: string
  doctors: DayColumn[]
  hours: DayHour[]
}

export const day = {
  get: (date: string, doctor: string, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    if (date) q.set('date', date)
    if (doctor) q.set('doctor', doctor)
    const tail = q.toString()
    return api.get<DayModel>(`/schedule/day${tail ? `?${tail}` : ''}`,
      signal ? { signal } : {})
  },
}
