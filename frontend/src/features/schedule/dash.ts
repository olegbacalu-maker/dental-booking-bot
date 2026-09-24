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

import { api } from '../../services/api'
import type { NewAppt, NewNote, NoteView, VisitCardView } from './day'
import type { SlotFormView } from './slot'

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
  /** ⛔ ПОЛНЫЙ текст (до 120). На панели он не виден нигде, кроме диалога:
   *  в блоке 40 знаков, в подсказке 80, а хранится 120. */
  text: string
  /** Подпись в блоке, 40 знаков. Обрезает сервер (`live-contract` › 6e). */
  label: string
  /** Состояние — им спрашивается кнопка в `note_actions` (C26.5.3-d). */
  status: string
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
  /** ⚠️ СНИМОК имени врача из самой записи, а не имя колонки: после
   *  переименования шапка колонки и диалог говорят РАЗНОЕ, и так надо. */
  doctor: string
  /** Пациент; `null` у легаси-строки — тогда ссылки на фишу нет. */
  pid: number | null
  /** Дневник визита уже заполнен. */
  rec: boolean
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

/** Кнопки исхода по состоянию: `{состояние: [кнопки]}`. ⛔ Слово кнопки и
 *  вопрос подтверждения приходят С СЕРВЕРА: второго словаря статусов в
 *  браузере нет, он разводился уже дважды (08-12, 08-16). */
export type DashActions = Record<string, {
  to: string
  cls: string
  label: string
  /** Непусто — спросить подтверждение этим текстом. */
  confirm: string
}[]>

/** Что нужно диалогу пустого часа. ⚠️ Имя `slotform`, а не `form`: у модели
 *  дня `form` несёт ещё врачей, их часы и предвыбор. */
export interface DashSlotForm {
  services: { id: string; label: string }[]
  /** Потолок поля «дата рождения» — сегодня В ЧАСАХ КЛИНИКИ. */
  birth_max: string
}

/** Живое состояние панели целиком — то, что везёт `GET /api/schedule/live`. */
export interface DashModel {
  screen: string
  /** Эхо дня, на который ответил сервер. ⭐ Адрес без `?date=` — это «сегодня
   *  сервера», и в полночь эхо меняется само: шапка и ссылки строятся ОТСЮДА,
   *  а не из адреса и не из узла. */
  date: string
  /** Подпись дня для шапки: «Jo 24.09.2026». ⛔ Строит СЕРВЕР (`_day_title`,
   *  та же, что у старой шапки): сокращения дней недели румынские, и второй их
   *  список в браузере разошёлся бы с первым молча (08-12, 08-16). Едет ОДНИМ
   *  конвертом с `date` — новый день приезжает датой и подписью разом. */
  day_label: string
  live: boolean
  canvas: DashCanvasModel
  agenda: DashAgenda
  tiles: DashTile[]
  occupancy: DashOccupancy
  minical: DashMiniCal
  /* ---- то, чем живут диалоги (C26.5.3-a) ---- */
  actions: DashActions
  note_actions: DashActions
  /** Часы, которыми может кончиться блокировка слота. */
  note_ends: number[]
  slotform: DashSlotForm
}

/**
 * ⛔ Сторож ТИПАМИ: блок канвы обязан подходить диалогу карточки целиком.
 *
 * Диалог у панели и у дня ОДИН (`CardDialog` принимает `VisitCardView`), и
 * держаться это должно построением, а не памятью. Пропадёт у блока поле —
 * `npm run typecheck` покраснеет ЗДЕСЬ, на одной строке с объяснением, а не
 * у клиники ссылкой на фишу, которой нет на одном экране из двух.
 */
type Fits<T extends true> = T
export type _DashApptFitsCard = Fits<DashAppt extends VisitCardView ? true : false>

/** ⛔ И то же самое у диалога пустого часа: он один на день и на панель, а
 *  конверты у них разные. Сузится `slotform` — покраснеет здесь. */
export type _DashSlotFormFitsDialog = Fits<DashSlotForm extends SlotFormView ? true : false>

/** ⛔ И у заметки: пропадёт `status` — диалог остался бы без кнопок молча,
 *  потому что `note_actions[undefined]` это просто пустой список. */
export type _DashNoteFitsDialog = Fits<DashNote extends NoteView ? true : false>

/** Адрес живого канала панели. Путь — без `/api`, как у `api.get`.
 *  ⛔ `date` — день АДРЕСА как есть: пусто значит «сегодня сервера», и так и
 *  уходит. Подставь сюда конкретный день, посчитанный при загрузке, — и
 *  вкладка, оставленная на ночь, утром опрашивала бы вчера. */
export function livePath(date: string): string {
  return `/schedule/live?screen=panel${date ? `&date=${encodeURIComponent(date)}` : ''}`
}

/**
 * Команды панели.
 *
 * ⛔ Ответ НЕ несёт состояния — ни на удаче, ни на отказе (`screen=panel`).
 * ⚠️ И параметр обязан быть ОБЪЯВЛЕН маршрутом, а не просто послан: FastAPI
 * молча игнорирует неизвестный параметр строки запроса, и такая команда
 * вернула бы полную модель дня, не сказав об этом ничем. Сторож — не тип
 * `void`, а проверка на сервере (`suite_panel_cmds`): типом это не ловится.
 * Состояние на живой поверхности выпускается ровно одной дверью — конвертом
 * с его отпечатком, — и въезжает одной: `apply` в `useLive`. Ответ действия
 * отпечатка не несёт, значит любое состояние в нём стало бы вторым
 * источником истины, не участвующим в протоколе. После команды экран просто
 * спрашивает канал: `refresh()`.
 * ⚠️ Отсюда же и тип `void`: брать из ответа нечего, и соблазна нет.
 */
export const dash = {
  /* ⚠️ Тело у записи и у заметки ТО ЖЕ, что шлёт день (`NewAppt`/`NewNote`):
     правило на сервере одно, и два описания одного тела разошлись бы молча —
     `nophone` остался бы намерением на одном экране и «пустым телефоном» на
     другом (08-16). ⛔ Отличие ровно одно и оно в АДРЕСЕ: `screen=panel`. */
  add: (date: string, body: NewAppt) =>
    api.post<void>(`/schedule/appointments${cmdQuery(date)}`, body),
  note: (date: string, body: NewNote) =>
    api.post<void>(`/schedule/notes${cmdQuery(date)}`, body),
  /* ⚠️ Тело переноса — то же, что у дня: {date, time, doctor}. День в нём
     ЕСТЬ и он не лишний: перенос бывает и на другой день (с недели), а
     маршрут один. */
  move: (date: string, id: number,
    body: { date: string; time: string; doctor: string }) =>
    api.post<void>(`/schedule/appointments/${id}/move${cmdQuery(date)}`, body),
  comment: (date: string, id: number, text: string) =>
    api.post<void>(`/schedule/appointments/${id}/comment${cmdQuery(date)}`,
      { comment: text }),
  status: (date: string, id: number, to: string) =>
    api.post<void>(`/schedule/appointments/${id}/status${cmdQuery(date)}`, { to }),
}

function cmdQuery(date: string): string {
  const q = new URLSearchParams({ screen: 'panel' })
  if (date) q.set('date', date)
  return `?${q.toString()}`
}
