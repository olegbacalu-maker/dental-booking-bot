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

export const settings = {
  hub: (signal?: AbortSignal): Promise<ApiResult<HubData>> =>
    api.get<HubData>('/settings/hub', signal ? { signal } : {}),
  lan: (signal?: AbortSignal): Promise<ApiResult<LanData>> =>
    api.get<LanData>('/settings/lan', signal ? { signal } : {}),
  lanSave: (mode: 'on' | 'off'): Promise<ApiResult<LanSaved>> =>
    api.post<LanSaved>('/settings/lan', { mode }),
  lanFirewall: (): Promise<ApiResult<{ asked: boolean }>> =>
    api.post<{ asked: boolean }>('/settings/lan/firewall', {}),
  faq: (signal?: AbortSignal): Promise<ApiResult<FaqData>> =>
    api.get<FaqData>('/settings/faq', signal ? { signal } : {}),
  hours: (signal?: AbortSignal): Promise<ApiResult<HoursData>> =>
    api.get<HoursData>('/settings/hours', signal ? { signal } : {}),
  hoursSave: (hours: Record<string, DayHours>): Promise<ApiResult<HoursData>> =>
    api.post<HoursData>('/settings/hours', { hours }),
}
