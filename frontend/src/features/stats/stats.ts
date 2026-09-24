import { api, type ApiResult } from '../../services/api'

/* Формы ответа — bot/app/modules/stats/api.py. Всё, что здесь строка с
   деньгами («4 200 MDL»), отформатировано СЕРВЕРОМ: разделитель тысяч и
   название валюты — часть локали, а не оформления, и второй форматировщик в
   TypeScript разошёлся бы с печатным отчётом кассы. */

/**
 * Сравнение с предыдущим периодом ТАКОЙ ЖЕ длины.
 *
 * ⛔ Предыдущий период называется ПО ИМЕНИ («față de săptămâna trecută»), а не
 * «perioada trecută»: безымянное сравнение уже дважды озадачивало Олега.
 */
export interface Trend {
  /** '' — не изменилось: слово вместо стрелки и цвета. */
  dir: '' | 'up' | 'dn'
  /** Имя значка; пусто там, где стрелки нет (сравнение с нулевым периодом). */
  icon: string
  /** '12%' | '+2 550 MDL' | '+3'; пусто при dir === ''. */
  value: string
  label: string
  /** ' (atunci 0)' — почему процентов нет. */
  note: string
}

export interface StatTile {
  key: string
  label: string
  value: number
  icon: string
  /** Цвет знака и спарклайна — переменная темы, не хекс. */
  tone: string
  soft: string
  /** Рост — это плохо (неявки, отмены): стрелка вверх, но цвет красный. */
  bad: boolean
  series: number[]
  trend: Trend
}

export interface StatPeriod {
  from: string
  to: string
  /** '15.09.2026 — 21.09.2026' — заголовок отбора. */
  label: string
  /** '15.09–21.09' — для подписей внутри карточек. */
  short: string
  days: number
}

export interface StatPreset {
  key: string
  label: string
  from: string
  to: string
}

export interface StatChart {
  labels: string[]
  values: number[]
  title: string
  /** '· 15.09 — 21.09.2026' — период прямо в заголовке карточки. */
  sub: string
  total: number
  total_trend: Trend
  present_pct: number
  noshow: number
  /** «cca 1 000 MDL pierdut» — оценка по прайсу, отформатирована сервером. */
  loss: string
  wait: { text: string; sub: string }
}

export interface StatSource {
  label: string
  value: number
  color: string
  pct: number
}

export interface StatMoney {
  key: string
  title: string
  /** '· bani reali, 15.09–21.09' — период прямо на карточке. */
  sub: string
  value: number
  text: string
  suffix: string
  trend: Trend
  note: { icon: string; t: string }[]
  link: { href: string; label: string; icon: string } | null
}

export interface StatDoctor {
  name: string
  off: boolean
  n: number
  came: number
  pres: number
  pct: number
}

export interface StatService {
  label: string
  cnt: number
  /** 'cca 1 500 MDL' — сервер же и склеил. */
  val: string
  pct: number
}

export interface StatEvent {
  text: string
  name: string
  patient_id: number | null
  who: string
  at: string
}

export interface StatsData {
  period: StatPeriod
  presets: StatPreset[]
  compare: string
  export_url: string
  tiles: StatTile[]
  chart: StatChart
  /** Один источник — не разбивка, а тавтология: у клиники без бота кольца нет. */
  sources: { show: boolean; total: number; parts: StatSource[] }
  occupancy: { pct: number; note: string }
  money: StatMoney[]
  doctors: StatDoctor[]
  services: StatService[]
  activity: StatEvent[]
  hint: string
}

export const stats = {
  /**
   * ⭐ Каждая НЕПУСТАЯ граница уходит сама по себе. Недостающую достраивает
   * `period()` сервера — одна функция на страницу и на JSON, поэтому
   * `?from=X` даёт X..сегодня и после F5, и в старой форме. Отбрось клиент
   * обе границы из-за одной пустой, и тот же адрес открыл бы в SPA «последние
   * 7 дней», а после перезагрузки — другой период.
   */
  get: (from: string, to: string, signal?: AbortSignal): Promise<ApiResult<StatsData>> => {
    const q = [
      from && `from=${encodeURIComponent(from)}`,
      to && `to=${encodeURIComponent(to)}`,
    ].filter(Boolean).join('&')
    return api.get<StatsData>(q ? `/stats?${q}` : '/stats', signal ? { signal } : {})
  },
}
