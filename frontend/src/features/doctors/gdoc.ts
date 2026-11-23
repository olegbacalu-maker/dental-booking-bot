import { api, type ApiResult } from '../../services/api'

/* Календарь врача в его Google: формы ответов — bot/app/modules/doctors/gcal_doctor.py (`view`,
   `overview`, `level_view`), маршруты — doctors/api.py. Состояние, кнопки (`can`) и все слова —
   сервера; экран решает только раскладку и что раскрыто. */

export type GdocState = 'off' | 'waiting' | 'on' | 'reconnect' | 'foreign' | 'premium' | 'readonly' | 'paused'
export type GdocLevelCode = 'time' | 'initials' | 'name'

export interface GdocWhy {
  code: string
  /** `plus` — связь стоит без права или в режиме чтения: серый замок, а не тревога. */
  tone: string
  text: string
  /** Вторая строка: что делать. */
  detail: string
  /** Только у неудачного прохода при живой связи. */
  at?: string
  when?: string
}

/** Слова блока карточки врача (`gcal_doctor.WORDS`); строки с числом и именем сервер отдаёт готовыми. */
export interface GdocWords {
  title: string; lead: string; hint: string; details: string
  connect: string; connect_here: string; reconnect: string; check: string; disconnect: string
  /** Вопрос перед «Deconectează» — с именем календаря. */
  disconnect_ask: string
  waiting_title: string; waiting_detail: string; reopen: string; cancel: string
  connected: string; calendar_label: string; last: string; all_in: string; last_ok: string
  /** «încă N programări în drum.»; пусто, когда всё доехало. */
  pending: string
  level_lead: string; level_link: string; premium_lead: string
}

/** Слова полосы «Calendarele medicilor în Google» и плашек врачей (`gcal_doctor.LIST_WORDS`). */
export interface GdocListWords {
  title: string; lead: string
  /** «Conectați: 1 din 3 medici». */
  count: string
  label: string; phone: string; change: string; only_dir: string; remote: string
  premium: string; premium_more: string; default: string; rewrite: string
  dlg_title: string; dlg_ack: string; dlg_ok: string; dlg_cancel: string
  /** Короткое слово плашки врача по состоянию; нет слова — плашки нет. */
  chip: Partial<Record<GdocState, string>>
}

export interface GdocView {
  state: GdocState
  account: string
  calendar: { id: string; name: string } | null
  /** Последняя удачная сверка; `when` — часы клиники словами. */
  last: { at: string; when: string } | null
  /** Сколько записей ещё не доехало до календаря (только у `on`). */
  pending: number
  why: GdocWhy | null
  level: { code: GdocLevelCode; label: string }
  notice: string
  privacy: { href: string; label: string }
  /** Путь к оплате Premium (у `premium` и `paused`). */
  premium: { href: string; label: string } | null
  /** Вход начат, браузер Windows ещё не вернулся. */
  waiting: boolean
  /** Открыто не с ПК программы: почему кнопки входа нет. */
  remote: string | null
  can: { connect: boolean; check: boolean; disconnect: boolean }
  words: GdocWords
}

export interface LevelChoice {
  code: GdocLevelCode
  label: string
  hint: string
  /** Заголовок события на этом уровне на образцовых данных — тем же построителем, что пишет сверка. */
  sample: string
  /** Непусто — уровень выбирается только через окно с галочкой этими словами. */
  warn: string
}

export interface LevelView {
  code: GdocLevelCode
  choices: LevelChoice[]
  can_set: boolean
  /** Почему менять нельзя (регистратура, второй ПК, режим чтения); пусто, когда можно. */
  lock: string
}

export interface GdocRow {
  state: GdocState
  account: string
  why: GdocWhy | null
}

export interface GdocList {
  doctors: Record<string, GdocRow>
  level: LevelView
  /** У клиники нет права: одна строка с путём к оплате вместо выбора, плашек нет. */
  premium: { href: string; label: string } | null
  words: GdocListWords
}

/** Ответ команды блока: вид после неё (и адрес Google у «Conectează»). */
export interface GdocReply {
  view: GdocView | null
  url?: string
}

const at = (dk: string) => `/gdoc/${encodeURIComponent(dk)}`

export const gdoc = {
  /** Плашки списка и выбор подробности; `null` — блока нет (демо, сервер, сборка без клиента). */
  list: (signal?: AbortSignal): Promise<ApiResult<GdocList | null>> =>
    api.get<GdocList | null>('/gdoc', signal ? { signal } : {}),
  /** Лёгкий опрос блока, пока врач входит в браузере. */
  view: (dk: string, signal?: AbortSignal): Promise<ApiResult<GdocView | null>> =>
    api.get<GdocView | null>(at(dk), signal ? { signal } : {}),
  connect: (dk: string): Promise<ApiResult<GdocReply>> => api.post<GdocReply>(`${at(dk)}/connect`, {}),
  cancel: (dk: string): Promise<ApiResult<GdocReply>> => api.post<GdocReply>(`${at(dk)}/cancel`, {}),
  check: (dk: string): Promise<ApiResult<GdocReply>> => api.post<GdocReply>(`${at(dk)}/check`, {}),
  disconnect: (dk: string): Promise<ApiResult<GdocReply>> => api.post<GdocReply>(`${at(dk)}/disconnect`, {}),
  setLevel: (level: GdocLevelCode, ack: boolean): Promise<ApiResult<{ level: LevelView }>> =>
    api.post<{ level: LevelView }>('/gdoc/level', { level, ack }),
}

/** Вид из ответа-отказа команды: сервер кладёт его и в конверт ошибки. */
export function viewOf(data: unknown): GdocView | null | undefined {
  if (!data || typeof data !== 'object' || !('view' in data)) return undefined
  return (data as GdocReply).view
}
