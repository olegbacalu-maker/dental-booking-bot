import { api } from '../../services/api'
import type { DashCanvasModel, DashMiniCal } from './dash'
import type { CallResult } from './desk'

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
  /** ⚠️ День его не читает — строка списка несёт свой. Объявлен потому, что
   *  тип описывает ОТВЕТ СЕРВЕРА: поле, которое приходит и молчит в типе, —
   *  это место, где контракт перестаёт быть контрактом. Читает его панель. */
  status: string
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
  /** Отметка звонка и можно ли её ставить (12.10) — поля сервера. */
  call: CallResult
  callable: boolean
  /** Ключ процедуры в clinic.json (пусто у легаси-строки) и можно ли её
   *  менять вообще (22.10) — `core.visits.service_fields`. ⛔ Списка услуг здесь
   *  нет: он одинаков у всех визитов врача и раздул бы каждый опрос главной —
   *  окно спрашивает его само (`day.serviceOptions`). */
  service_id: string
  service_edit: boolean
}

/**
 * Что нужно диалогу заметки стойки — и ничего сверх.
 *
 * ⭐ Узкий вид, под который структурно ложатся `DashNote` (панель) и `DayNote`
 * (день), — та же раскладка, что у `VisitCardView`.
 * ⛔ Поля, которое ПРАВЯТ, здесь нет и быть не может: текст заметки не
 * редактируется нигде в программе. Он пишется один раз при вставке
 * (`db._insert_note`), и ни один `UPDATE appointments` не трогает колонку
 * `service` — маршрута для правки не существует. Поле ввода в этом диалоге
 * завело бы правило, которого на сервере нет, а изобретать серверные правила
 * в шаге миграции запрещено.
 */
export interface NoteView {
  time: string
  dur: number
  /** ПОЛНЫЙ текст (до 120). ⛔ Никогда `label` (40) и никогда `title` (80). */
  text: string
  /** По нему берётся кнопка из `note_actions`. ⚠️ В матрице заметки два
   *  состояния из шести: у неё нет прихода и исхода, есть «убрать» и
   *  «вернуть». Чужой статус честно даёт ПУСТОЙ список кнопок. */
  status: string
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
  /** Отметка звонка-подтверждения (12.10) и можно ли её ставить — сервер,
   *  `core.visits.call_fields`; дату в браузере не считает никто. */
  call: CallResult
  callable: boolean
  /** Процедура и можно ли её менять (22.10) — `core.visits.service_fields`. */
  service_id: string
  service_edit: boolean
}

/** Услуга, на которую можно сменить процедуру визита: ключ clinic.json и
 *  подпись (22.10, `GET …/service`). */
export interface ServiceOption {
  id: string
  label: string
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
  /** Рисовать ли галочку «SMS reminder» (`day.sms_box`: пакет работает и у
   *  вошедшего право SMS). Нет поля — галочки нет. */
  sms?: boolean
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
  /** Вид статуса с учётом звонка (03.10): `confirmed` → `called`/`noanswer`
   *  после отметки в «De confirmat». Класс плашки — по нему, кнопки — по `status`. */
  status_view: string
  status_label: string
  reminded: boolean
  /** Напомнили именно SMS (S5): подсказка колокольчика называет канал. */
  reminded_sms: boolean
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
  /** Подпись дня для шапки: «Mi 07.10.2026». ⛔ Строит СЕРВЕР (`day.day_title`,
   *  та же, что у старой шапки и у панели дня): дни недели по-румынски знает
   *  только он. */
  day_label: string
  /** Дата словами для подзаголовка (08.10): «Joi, 8 octombrie 2026» — тоже сервер. */
  day_long: string
  /** Канва дня — та же, что у панели (`canvas.model`, 06.10): экран рисует её
   *  тем же компонентом, что «Panoul principal», а не таблицей. У дня врача в
   *  ней одна колонка (плюс сироты его легаси-строк). ⛔ Ключ колонки у канвы
   *  СВОЙ, не тот, что у таблицы (`doctors`/`hours`), и подменять одно другим
   *  нельзя — разбор в `canvas.model`. */
  canvas: DashCanvasModel
  /** Показывать ли «Sursă» в «Lista zilei»: только у клиники с ботом
   *  (`tg_configured`), как и весь остальной интерфейс бота. Без бота там
   *  везде одно слово «manual», и колонка ничего не различает. */
  source_col: boolean
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
  /** Только у дня ОДНОГО врача (22.10, вариант A Олега): что карточка визита
   *  знает о пациенте, по id визита. ⛔ Не в блоках канвы: они едут в каждом
   *  конверте живой главной, и канва общего дня обязана совпадать с ней. */
  extras?: Record<string, VisitFacts>
  /** Только у дня врача (22.10, вариант H): календарь кнопки даты в шапке —
   *  ссылки на `/admin/doctor/{dk}`, точки только его записей. */
  minical?: DashMiniCal
}

/** Строка колонки рисков: atenționare фиши или часть анамнеза. Сведены без
 *  дублей СЕРВЕРОМ (`core.risks.merge`) — второго правила здесь нет. Тон —
 *  `red` | `orange` | `amber` | `grey`, значок — имя `layout._I` (пусто — без). */
export interface VisitRisk {
  tone: string
  icon: string
  text: string
  title: string
}

/** Факты карточки визита дня врача (`routes._visit_facts`). ⛔ «Сейчас» в них
 *  нет: прошлый визит — последний ДО этого, давность считает экран от дня
 *  экрана по `last.date`. */
export interface VisitFacts {
  /** Какой это визит пациента: 1 — первый («Pacient nou»). */
  nth: number
  /** Прошлый визит: ISO-дата и что делали (графа «Tratament», иначе услуга). */
  last: { date: string; what: string } | null
  risks: VisitRisk[]
  /** Собран ли анамнез. */
  anam: boolean
  /** Активный план: зуб, процедура, «în lucru». */
  plan: { tooth: number | null; proc: string; work: boolean }[]
  /** Долг: плюс — должен, минус — аванс. */
  debt: number
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
  /** Галочка «SMS reminder» — только ТРОНУТАЯ (`SmsBox`); нет поля —
   *  `sms_off` пациента сервер не трогает. */
  sms?: boolean
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

  /** Запись из окна шапки вне дня журнала (`NewApptHost`, 22.10): дня экрана
   *  у окна нет, и состояние ему не нужно — `screen=new_appt` (`_NO_STATE`
   *  сервера), ответ — код и слово. Тело — то же `NewAppt`: правило одно. */
  record: (body: NewAppt) =>
    api.post<void>('/schedule/appointments?screen=new_appt', body),

  /** С чем стоит галочка «SMS reminder» для этого номера: согласие того, в
   *  чью карточку ляжет запись, у нового — `true`. Номер — телом, не адресом. */
  smsOf: (phone: string, signal?: AbortSignal) =>
    api.post<{ sms: boolean }>('/schedule/sms-of', { phone }, signal ? { signal } : {}),

  note: (at: string, doctor: string, f: string, body: NewNote) =>
    api.post<DayModel>(`/schedule/notes${screen(at, doctor, f)}`, body),

  comment: (at: string, doctor: string, f: string, id: number, comment: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/comment${screen(at, doctor, f)}`, { comment }),

  status: (at: string, doctor: string, f: string, id: number, to: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/status${screen(at, doctor, f)}`, { to }),

  /** На какие услуги можно сменить процедуру визита (22.10): окно спрашивает
   *  при открытии. Правило — сервера (`visits.service_refusal`), правду при
   *  смене говорит POST под замком. */
  serviceOptions: (id: number, signal?: AbortSignal) =>
    api.get<{ service_id: string; options: ServiceOption[] }>(
      `/schedule/appointments/${id}/service`, signal ? { signal } : {}),

  /** Смена процедуры у стоящей записи (22.10): ответ — свежий день, как у
   *  комментария. */
  service: (at: string, doctor: string, f: string, id: number, serviceId: string) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/service${screen(at, doctor, f)}`,
      { service_id: serviceId }),

  move: (at: string, doctor: string, f: string, id: number,
         body: { date: string; time: string; doctor: string }) =>
    api.post<DayModel>(
      `/schedule/appointments/${id}/move${screen(at, doctor, f)}`, body),

  /** Отметка звонка-подтверждения из карточки и меню (12.10) — тот же маршрут,
   *  что у «De confirmat» панели; дню журнала он отвечает свежим днём. */
  call: (at: string, doctor: string, f: string, id: number, result: CallResult) =>
    api.post<DayModel>(`/schedule/desk/call/${id}${screen(at, doctor, f)}`, { result }),
}
