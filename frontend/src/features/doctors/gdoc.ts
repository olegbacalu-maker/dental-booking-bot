import type { ServerNotice } from '../../components/Notice'
import { api, type ApiResult } from '../../services/api'

/* Календарь врача в его Google: формы ответов — bot/app/modules/doctors/gcal_doctor.py (`view`,
   `overview`, `level_view`), маршруты — doctors/api.py. Состояние, кнопки (`can`) и все слова —
   сервера; экран решает только раскладку и что раскрыто. */

export type GdocState = 'off' | 'waiting' | 'on' | 'reconnect' | 'foreign' | 'premium' | 'readonly' | 'paused'
export type GdocLevelCode = 'time' | 'initials' | 'name'

export interface GdocWhy extends ServerNotice {
  /** Вторая строка: что делать. */
  detail: string
  /** Только у неудачного прохода при живой связи. */
  at?: string
  when?: string
}

export interface GdocWords {
  title: string; lead: string; hint: string; details: string; notice?: string
  connect: string; reconnect: string; disconnect: string; disconnect_ok: string; disconnect_ask: string
  check: string; reopen: string; cancel: string
  waiting_title: string; waiting_detail: string
  connected: string; calendar_label: string; last_ok: string
  /** Подпись перед числом ещё не доехавших записей. */
  pending: string
  level_label: string; premium_lead: string
  list_title: string; level_title: string; level_ack: string; level_save: string
  /** Готовая строка «сколько врачей подключено»; нет — строки нет. */
  count?: string
  level_default?: string
  rewrite?: string
  /** Короткое слово плашки врача в списке по состоянию; нет слова — плашки нет. */
  chip?: Partial<Record<GdocState, string>>
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
  /** Открыто не с ПК программы. */
  remote: ServerNotice | null
  can: { connect: boolean; check: boolean; disconnect: boolean }
  words: GdocWords
}

export interface LevelChoice {
  code: GdocLevelCode
  label: string
  hint: string
  /** Заголовок события на этом уровне на образцовых данных; нет — экран показывает `hint`. */
  sample?: string
  /** Непусто — уровень выбирается только через окно с галочкой этими словами. */
  warn: string
}

export interface LevelView {
  code: GdocLevelCode
  choices: LevelChoice[]
  can_set: boolean
  /** Почему менять нельзя (регистратура, второй ПК); пусто, когда можно. */
  lock?: string
}

export interface GdocRow {
  state: GdocState
  account: string
  why: GdocWhy | null
}

export interface GdocList {
  doctors: Record<string, GdocRow>
  level: LevelView
  words: GdocWords
  /** У клиники нет права: одна строка с путём к оплате вместо выбора. */
  premium?: { href: string; label: string } | null
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
