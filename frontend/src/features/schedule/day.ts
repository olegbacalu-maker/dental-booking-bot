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
  /** ⛔ Полное значение — ИЗ НЕГО правят (диалог карточки). */
  comment: string
  /** Обрезок для ячейки сетки, 60 знаков. ⛔ Не писать обратно: сервер примет
   *  и укоротит текст в базе без единой правки человеком (08-16). */
  comment_cut: string
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
/**
 * Что нужно диалогу карточки — и ничего сверх.
 *
 * ⭐ Узкий вид, под который структурно ложатся и `DayCard` (день), и
 * `DashAppt` (панель). Диалог у двух экранов ОДИН: заведи второй компонент —
 * и на одном экране у визита появится ссылка на фишу, а на другом нет, и
 * увидеть это можно, только открыв оба.
 */
export interface VisitCardView {
  time: string
  name: string
  service: string
  doctor: string
  phone: string
  age: number | null
  /** ПОЛНОЕ значение: из него правят. Никогда не `comment_cut`. */
  comment: string
  status: string
  pid: number | null
  rec: boolean
}

export interface DayCard {
  name: string
  phone: string
  service: string
  doctor: string
  time: string
  comment: string
  age: number | null
  /** Состояние: по нему берётся набор кнопок из `actions`.
   *  ⚠️ Имя `status`, как в блоке сетки: два имени одного состояния в двух
   *  словарях — та самая пара 08-12 и 08-16. */
  status: string
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

/** Строка «Lista zilei». ⚠️ Комментарий здесь УЖЕ обрезан до 80 знаков:
 *  полный живёт в `cards`, и править надо его. */
export interface DayListRow {
  id: number
  is_note: boolean
  time: string
  name: string
  age: number | null
  phone: string
  service: string
  urgent: boolean
  /** Полное значение; строка списка печатает `comment_cut` (80). */
  comment: string
  comment_cut: string
  /** Снимок имени врача из самой записи, а не колонка сетки. */
  doctor: string
  source: string
  source_label: string
  status: string
  status_label: string
  reminded: boolean
  rec: boolean
}

/** Отбор плитки панели дня: режет СПИСОК, сетку не трогает. */
export interface DayFilter {
  key: string
  label: string
  count: number
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
  /** Кнопки заметки — своя матрица: у неё «убрать» и «вернуть», не исходы. */
  note_actions: Record<string, StatusAction[]>
  list: DayListRow[]
  filter: DayFilter | null
}

/** Где мы стоим: свежий день в ответе действия приезжает для ЭКРАНА. */
function screen(date: string, doctor: string, f = ''): string {
  const q = new URLSearchParams()
  if (date) q.set('date', date)
  if (doctor) q.set('doctor', doctor)
  if (f) q.set('f', f)
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
  get: (date: string, doctor: string, f = '', signal?: AbortSignal) =>
    api.get<DayModel>(`/schedule/day${screen(date, doctor, f)}`,
      signal ? { signal } : {}),

  add: (at: string, doctor: string, f: string, body: NewAppt) =>
    api.post<DayModel>(`/schedule/appointments${screen(at, doctor, f)}`, body),

  note: (at: string, doctor: string, f: string, body: NewNote) =>
    api.post<DayModel>(`/schedule/notes${screen(at, doctor, f)}`, body),

  comment: (at: string, doctor: string, f: string, id: number, comment: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/comment${screen(at, doctor, f)}`, { comment }),

  status: (at: string, doctor: string, f: string, id: number, to: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/status${screen(at, doctor, f)}`, { to }),

  move: (at: string, doctor: string, f: string, id: number,
         body: { date: string; time: string; doctor: string }) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/move${screen(at, doctor, f)}`, body),
}
