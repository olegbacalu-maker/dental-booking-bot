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

/** Карточка визита — ПОЛНАЯ, включая комментарий целиком (в сетке он обрезан
 *  до 60). Отменённые записи карточку имеют, хотя из сетки уходят: их
 *  открывают, чтобы вернуть. */
export interface DayCard {
  name: string
  phone: string
  service: string
  doctor: string
  time: string
  comment: string
  age: number | null
  /** Состояние: по нему берётся набор кнопок из `actions`. */
  st: string
  pid: number | null
  /** Дневник визита уже заполнен. */
  rec: boolean
}

/** Кнопка исхода — сервер говорит и слово, и класс, и нужен ли вопрос. */
export interface StatusAction {
  to: string
  cls: string
  label: string
  /** Непустое — спросить подтверждение этим текстом. */
  confirm: string
}

/** Что предлагает форма записи. `doctors` — НЕ колонки сетки: выключенный
 *  врач остаётся колонкой, пока у него есть записи, а записать в него нельзя. */
export interface DayForm {
  doctors: DayColumn[]
  /** Часы по врачам; пустое окно врача подменено часами клиники. */
  times: Record<string, string[]>
  /** Часы клиники — ими живёт форма, когда активных врачей нет вовсе. */
  hours: string[]
  services: { id: string; label: string }[]
  doctor: string
  time: string
  birth_max: string
}

export interface DayModel {
  date: string
  doctors: DayColumn[]
  hours: DayHour[]
  /** `null` — формы нет (страница выключенного врача). */
  form: DayForm | null
  /** Часы, которыми может кончиться блокировка слота. */
  note_ends: number[]
  cards: Record<string, DayCard>
  actions: Record<string, StatusAction[]>
}

/** Где мы стоим: свежий день в ответе действия приезжает для ЭКРАНА. */
function screen(date: string, doctor: string): string {
  const q = new URLSearchParams()
  if (date) q.set('date', date)
  if (doctor) q.set('doctor', doctor)
  const tail = q.toString()
  return tail ? `?${tail}` : ''
}

export interface NewAppt {
  date: string
  time: string
  doctor: string
  service: string
  name: string
  phone: string
  nophone: boolean
  birth: string
}

export interface NewNote {
  date: string
  time: string
  doctor: string
  text: string
  until: number
}

export const day = {
  get: (date: string, doctor: string, signal?: AbortSignal) =>
    api.get<DayModel>(`/schedule/day${screen(date, doctor)}`,
      signal ? { signal } : {}),

  add: (at: string, doctor: string, body: NewAppt) =>
    api.post<DayModel>(`/schedule/appointments${screen(at, doctor)}`, body),

  note: (at: string, doctor: string, body: NewNote) =>
    api.post<DayModel>(`/schedule/notes${screen(at, doctor)}`, body),

  comment: (at: string, doctor: string, id: number, comment: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/comment${screen(at, doctor)}`, { comment }),

  status: (at: string, doctor: string, id: number, to: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/status${screen(at, doctor)}`, { to }),

  move: (at: string, doctor: string, id: number,
         body: { date: string; time: string; doctor: string }) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/move${screen(at, doctor)}`, body),
}
