/**
 * Панель дня (`/admin`) — контракт данных живого канала.
 *
 * ⛔ Это НЕ модель дня (`day.ts`) другими словами. Ключ колонки здесь свой:
 * легаси-строка без `doctor_id`, но с именем ЖИВОГО врача, получает тут
 * ОТДЕЛЬНУЮ колонку с формой relink, а день сливает её в колонку врача.
 * Собери панель по модели дня — визит выпавшего из справочника врача исчезнет
 * с экрана, а час будет выглядеть свободным (разбор — `admin-contract.md`).
 *
 * ⚠️ Чего в модели НЕТ намеренно: линии «сейчас» и ступеней сжатия блока.
 * Первая меняется непрерывно, вторые ставятся ПО ЗАМЕРУ в браузере — высоту
 * ряда решает окно, и порог числом соврал бы на одном из двух мониторов.
 * Обе живут в `dashFx.ts`.
 */

/** Полоска «закрыто» вместо срезанных крайних часов. */
export interface DashBand {
  from: string
  to: string
}

interface BlockBase {
  id: number
  time: string
  /** Минуты от полуночи и длительность — те же поля, что у переноса. */
  min: number
  dur: number
  busy: boolean
  movable: boolean
  /** Доли ячейки: `top` от `base_min`, `height` от длительности. */
  top: number
  height: number
  /** Место в кластере пересечений: `col`-я из `of`. */
  col: number
  of: number
  /** Подсказка. У короткого блока она единственное, что отвечает «кто это». */
  title: string
}

export interface DashNote extends BlockBase {
  kind: 'note'
  /** Полный текст заметки — из него правят. */
  text: string
  /** Подпись в блоке, 40 знаков. Обрезает сервер (`live-contract` › 6e). */
  label: string
}

export interface DashAppt extends BlockBase {
  kind: 'appt'
  name: string
  service: string
  phone: string
  status: string
  /** Слово статуса — сервера; второго словаря в клиенте нет. */
  status_label: string
  urgent: boolean
  source: string
  /** Полное значение. */
  comment: string
  /** Обрезок для ячейки сетки, 60 знаков. */
  comment_cut: string
  age: number | null
  clickable: boolean
  bg: string
  bar: string
  /** ⛔ Только ОТМЕТКА времени: минуты считает браузер, иначе серверная
   *  строка меняла бы отпечаток каждую минуту. */
  wait_since: number | null
}

export type DashBlock = DashNote | DashAppt

export interface DashColumn {
  key: string
  /** `null` у колонки-сироты: врача с таким именем в справочнике уже нет. */
  id: string | null
  name: string
  orphan: boolean
  spec: string
  off: boolean
  hue: string
  photo: string
  initials: string
  room?: string
  phone?: string
  /** Пациенты. ⛔ Заметку стойки не считает. */
  count: number
  /** Ближайший свободный час — а ЭТО смотрит на занятость, и заметка её
   *  занимает. Два числа шапки питаются разными списками намеренно. */
  free: string | null
  /** ⚠️ `pct` НЕ обрезан сотней: «130%» — единственный признак перебронирования. */
  occupancy: { busy: number; cap: number; pct: number } | null
  title: string
  /** По одному признаку на ряд часа: принимает ли он клик и перенос. */
  cells: boolean[]
  blocks: DashBlock[]
  relink: { name: string; options: { id: string; name: string }[] } | null
}

export interface DashCanvasModel {
  date: string
  /** Ни графика, ни записей: сетки нет вовсе. */
  empty: boolean
  base_min: number | null
  /** Больше четырёх колонок — карточка врача ужимается. */
  tight: boolean
  hours: { h: number; label: string; now: boolean }[]
  bands: { top: DashBand | null; bottom: DashBand | null }
  columns: DashColumn[]
}

/** Подпись под цифрой плитки. Четыре формы, и свести их к одной нельзя:
 *  они отвечают на разные вопросы. */
export type DashSub =
  | { kind: 'same'; diff: 0; dir: null; text: string }
  | { kind: 'delta'; diff: number; dir: 'up' | 'dn'; text: string }
  | { kind: 'static'; text: string }
  | { kind: 'bot_new'; new: number; text: string }

export interface DashTile {
  key: string
  label: string
  value: number
  icon: string
  soft: string
  tone: string
  filter: string
  href: string
  cls: string
  sub: DashSub
  series: number[]
}

export interface DashAgendaItem {
  id: number
  time: string
  dur: number
  name: string
  service: string
  status: string
  badge: { cls: string; label: string }
  urgent: boolean
  bar: string
  /** `future` / `current` / `past`, и `null` в ЧУЖОМ дне: там «прошло»
   *  не значит ничего, а тусклый список читался бы как отменённый. */
  state: 'future' | 'current' | 'past' | null
  clickable: boolean
  patient_id: number | null
  wait_since: number | null
}

export interface DashAgenda {
  count: number
  today: boolean
  items: DashAgendaItem[]
}

export interface DashOccupancy {
  label: string
  icon: string
  soft: string
  tone: string
  value: number
  series: number[]
  /** «было → стало», а не разница в пунктах: п.п. пришлось объяснять даже
   *  директору, и регистратура не обязана знать эту единицу. */
  from: { label: string; value: string }
  to: { label: string; value: string }
  dir: 'up' | 'dn' | null
}

export interface DashMiniCalCell {
  date: string
  day: number
  /** Три НЕЗАВИСИМЫЕ метки: один день бывает сразу и сегодняшним, и выбранным. */
  other: boolean
  today: boolean
  selected: boolean
  href: string
}

export interface DashMiniCal {
  title: string
  weekdays: string[]
  /** Недель пять ИЛИ шесть — это не константа. */
  weeks: DashMiniCalCell[][]
  prev: { date: string; href: string }
  next: { date: string; href: string }
}

/** Живое состояние панели целиком — то, что везёт `GET /api/schedule/live`. */
export interface DashModel {
  screen: string
  date: string
  live: boolean
  canvas: DashCanvasModel
  agenda: DashAgenda
  tiles: DashTile[]
  occupancy: DashOccupancy
  minical: DashMiniCal
}

/** Адрес живого канала панели. Путь — без `/api`, как у `api.get`. */
export function livePath(date: string): string {
  return `/schedule/live?screen=panel${date ? `&date=${encodeURIComponent(date)}` : ''}`
}
