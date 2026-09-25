import { api, type ApiResult } from '../../services/api'

/* Формы ответов — bot/app/modules/settings/api.py. Всё, что здесь HTML
   (справка FAQ, проза страницы «Acces din rețea»), — текст СЕРВЕРА из тех же
   строк, что рисует старая страница: не данные пользователя. */

/** Кусок строки состояния плитки: текст, иконка с текстом (и тоном), точка цвета. */
export interface HintPart {
  t?: string
  icon?: string
  tone?: 'amber' | 'red'
  dot?: string
}

export interface HubTile {
  href: string
  icon: string
  tone: string
  label: string
  hint: HintPart[]
}

export interface HubData {
  tiles: HubTile[]
}

export interface LanData {
  enabled: boolean
  ip: string
  port: number
  url: string
  /** null — проверить нечем (нет netsh). */
  firewall: boolean | null
  blocks: { intro: string; status: string; firewall: string; tips: string }
}

export interface LanSaved {
  enabled: boolean
  /** Программа сама закрывается и стартует заново (планировщик отработал). */
  restart: boolean
  /** Что сказать человеку про перезапуск; пусто вне настольного издания. */
  text: string
  note: string
}

export interface FaqItem {
  icon: string
  question: string
  /** HTML ответа — серверный текст с иконками, как на старой странице. */
  answer: string
}

export interface FaqData {
  items: FaqItem[]
  contact: string
}

/** null — закрыто; [от, до]; [от, до, пауза от, пауза до]. Часы целые. */
export type DayHours = null | [number, number] | [number, number, number, number]

export interface HoursData {
  hours: Record<string, DayHours>
  range: { min: number; max: number }
  days: { key: string; label: string }[]
}

/** Строка таблицы услуг — так, как её показывала старая страница. */
export interface ServiceEntry {
  id: string
  ro: string
  ru: string
  price: string
  duration: number
  /** Ключ палитры или пусто (авто). */
  color: string
  urgent: boolean
  /** id врачей; пусто = все. */
  docs: string[]
}

export interface ServicesData {
  services: ServiceEntry[]
  palette: Record<string, string>
  durations: number[]
  doctors: { id: string; name: string }[]
}

export interface ThemeStyle {
  key: string
  label: string
  hint: string
  vars: Record<string, string>
}

/** Вариант меню (фирменное / нейтральное): переменные :root для предпросмотра. */
export interface ThemeMenu {
  key: string
  label: string
  hint: string
  vars: Record<string, string>
}

/** Шрифт интерфейса: набор семейств — значение `--font`. */
export interface ThemeFont {
  key: string
  label: string
  hint: string
  stack: string
}

export interface ThemeData {
  style: string
  primary: string
  custom: boolean
  menu: string
  font: string
  styles: ThemeStyle[]
  menus: ThemeMenu[]
  fonts: ThemeFont[]
  presets: { hex: string; name: string }[]
  /** Палитры сервера: стиль → hex набора → переменные :root. */
  palettes: Record<string, Record<string, Record<string, string>>>
  logo: string | null
  logo_topbar: boolean
  logo_max_mb: number
}

/** Те же поля, что у старой формы темы. */
export interface ThemeForm {
  style: string
  /** hex из набора или 'custom'. */
  primary: string
  custom: string
  logo_topbar: boolean
  menu: string
  font: string
}

export interface UserRow {
  id: string
  name: string
  role: string
  doctor_id: string
  /** «13.08.2026 14:02» или пусто — с сервера, в часах клиники. */
  last_login: string
}

export interface SecurityData {
  users: UserRow[]
  /** Подписи ролей: director / receptie / medic. */
  roles: Record<string, string>
  doctors: { id: string; name: string }[]
  /** id вошедшего — свою учётку удалить нельзя. */
  me: string
  pin: { min: number; max: number }
}

/** Те же поля, что у формы учётки: pin пустой = не менять. */
export interface UserForm {
  uid: string
  name: string
  role: string
  doctor_id: string
  pin: string
}

/** Что показывает раздел шифрования. `cloud` — не состояние ключа, а издание:
 *  у PostgreSQL файла базы нет вовсе. Четвёртого состояния («ключ не читается»)
 *  здесь не бывает — оно уводит программу в режим восстановления при старте. */
export type CryptState = 'cloud' | 'off' | 'pending' | 'on'

export interface CryptData {
  state: CryptState
  /** Проза состояния — серверный текст теми же кусками, что у старой страницы.
   *  Пустая строка значит «в этом состоянии блока нет». */
  blocks: { status: string; what: string; cost: string; limit: string; note: string }
  /** Адрес печатного листа восстановления. Он остаётся серверной страницей. */
  sheet: string
}

export interface CryptPrepared {
  sheet: string
}

export interface CryptStopped {
  /** Программа сама закрывается и стартует заново (планировщик отработал). */
  restart: boolean
  /** Что сказать человеку про перезапуск; пусто вне настольного издания. */
  text: string
  note: string
}

/** Что программа знает про обновление. Слова — серверные: в них едут номера
 *  версий и причина, по которой файла ещё нет. */
export interface SystemUpdate {
  state: 'self' | 'pending' | 'link' | 'fresh' | 'unknown' | 'checking'
  /** Имя значка из icons.ts; пусто — значка у этого состояния нет. */
  icon: string
  text: string
  latest: string
  /** Адрес страницы релиза; непуст только когда скачивать надо руками. */
  url: string
}

export interface SystemData {
  version: string
  db: string
  /** Путь и объяснение, что в нём лежит. Пустой путь — строки нет вовсе. */
  folder: { path: string; hint: string }
  /** Строка канала бота, HTML-кусок сервера; пусто, пока раздел заморожен. */
  telegram: string
  update: SystemUpdate
  /** Непусто только на НЕ-stable: этот компьютер видит версии раньше клиник. */
  channel: { name: string; warn: string; note: string } | null
  access: { icon: string; text: string }
  /** null вне настольного издания: у облака диск не наш. */
  bitlocker: { tone: string; icon: string; text: string } | null
  feedback: string
  /** Два абзаца о том, что программа работает локально (RO и RU). */
  privacy: string
  /**
   * Запись в «Программах и компонентах» (P4.1). `found=false` — установка
   * копированием, в реестре её нет и чинить нечего. `stale` — версия там
   * отстала: правка требует прав администратора, поэтому это СОСТОЯНИЕ, а не
   * то, что программа поправит сама.
   */
  uninstall: { found: boolean; version: string; stale: boolean; hive: string }
}

export interface BackupData {
  min_pass: number
  filename: string
}

export const settings = {
  security: (signal?: AbortSignal): Promise<ApiResult<SecurityData>> =>
    api.get<SecurityData>('/settings/security', signal ? { signal } : {}),
  userSave: (form: UserForm): Promise<ApiResult<SecurityData>> =>
    api.post<SecurityData>('/settings/users', form),
  userDelete: (uid: string): Promise<ApiResult<SecurityData>> =>
    api.post<SecurityData>(`/settings/users/${encodeURIComponent(uid)}/delete`, {}),
  pinChange: (old_pin: string, new1: string, new2: string): Promise<ApiResult<undefined>> =>
    api.post<undefined>('/settings/pin', { old_pin, new1, new2 }),
  backup: (signal?: AbortSignal): Promise<ApiResult<BackupData>> =>
    api.get<BackupData>('/settings/backup', signal ? { signal } : {}),
  services: (signal?: AbortSignal): Promise<ApiResult<ServicesData>> =>
    api.get<ServicesData>('/settings/services', signal ? { signal } : {}),
  servicesSave: (services: ServiceEntry[]): Promise<ApiResult<ServicesData>> =>
    api.post<ServicesData>('/settings/services', { services }),
  theme: (signal?: AbortSignal): Promise<ApiResult<ThemeData>> =>
    api.get<ThemeData>('/settings/theme', signal ? { signal } : {}),
  themePalette: (hex: string, style: string): Promise<ApiResult<Record<string, string>>> =>
    api.get<Record<string, string>>(
      `/settings/theme/palette?c=${encodeURIComponent(hex)}&style=${encodeURIComponent(style)}`,
    ),
  themeSave: (form: ThemeForm): Promise<ApiResult<ThemeData>> =>
    api.post<ThemeData>('/settings/theme', form),
  themeLogo: (file: File): Promise<ApiResult<ThemeData>> => {
    const fd = new FormData()
    fd.append('file', file)
    return api.postForm<ThemeData>('/settings/theme/logo', fd)
  },
  themeLogoDelete: (): Promise<ApiResult<ThemeData>> =>
    api.post<ThemeData>('/settings/theme/logo/delete', {}),
  hub: (signal?: AbortSignal): Promise<ApiResult<HubData>> =>
    api.get<HubData>('/settings/hub', signal ? { signal } : {}),
  lan: (signal?: AbortSignal): Promise<ApiResult<LanData>> =>
    api.get<LanData>('/settings/lan', signal ? { signal } : {}),
  lanSave: (mode: 'on' | 'off'): Promise<ApiResult<LanSaved>> =>
    api.post<LanSaved>('/settings/lan', { mode }),
  lanFirewall: (): Promise<ApiResult<{ asked: boolean }>> =>
    api.post<{ asked: boolean }>('/settings/lan/firewall', {}),
  system: (signal?: AbortSignal): Promise<ApiResult<SystemData>> =>
    api.get<SystemData>('/settings/system', signal ? { signal } : {}),
  systemCheck: (): Promise<ApiResult<SystemData>> =>
    api.post<SystemData>('/settings/system/check', {}),
  /** Попросить Windows поправить запись установщика: показывает окно UAC.
      ⚠️ Ответ — свежая модель, а НЕ «сделано»: итог окна серверу не виден. */
  uninstallSync: (): Promise<ApiResult<SystemData>> =>
    api.post<SystemData>('/settings/system/uninstall-sync', {}),
  crypt: (signal?: AbortSignal): Promise<ApiResult<CryptData>> =>
    api.get<CryptData>('/settings/crypt', signal ? { signal } : {}),
  cryptPrepare: (): Promise<ApiResult<CryptPrepared>> =>
    api.post<CryptPrepared>('/settings/crypt/prepare', {}),
  cryptStop: (): Promise<ApiResult<CryptStopped>> =>
    api.post<CryptStopped>('/settings/crypt/off', {}),
  faq: (signal?: AbortSignal): Promise<ApiResult<FaqData>> =>
    api.get<FaqData>('/settings/faq', signal ? { signal } : {}),
  hours: (signal?: AbortSignal): Promise<ApiResult<HoursData>> =>
    api.get<HoursData>('/settings/hours', signal ? { signal } : {}),
  hoursSave: (hours: Record<string, DayHours>): Promise<ApiResult<HoursData>> =>
    api.post<HoursData>('/settings/hours', { hours }),
}
