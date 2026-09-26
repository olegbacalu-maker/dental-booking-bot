import { api, type ApiResult } from '../../services/api'
import type { StatusAction } from './day'

/* Экран «у кресла» (docs/dentpilot-2/chair-mode.md). Форма ответа —
   bot/app/modules/schedule/api.py › api_chair, правило «кто в кресле» —
   schedule/chair.py. ⛔ Экран ничего не решает сам: кто в кресле, кто «не
   завершён», кто в очереди и какие кнопки у статуса — ответ сервера. */

/** Строка — та же, что у повестки панели (`panel.agenda`): слово статуса
    приходит готовым, второго словаря статусов в браузере нет. */
export interface ChairItem {
  id: number
  time: string
  dur: number
  name: string
  service: string
  status: string
  badge: { cls: string; label: string }
  urgent: boolean
  bar: string
  state: 'future' | 'current' | 'past' | null
  clickable: boolean
  patient_id: number | null
  wait_since: number | null
}

export interface ChairDoctor {
  dk: string
  name: string
}

export interface ChairData {
  date: string
  today?: boolean
  doctors: ChairDoctor[]
  /** `null` — врач не выбран: ни в адресе, ни привязкой учётки. */
  doctor: ChairDoctor | null
  chair: ChairItem | null
  /** Заведены в кабинет раньше того, кто в кресле, и не завершены. */
  stale: ChairItem[]
  queue: ChairItem[]
  actions: Record<string, StatusAction[]>
}

const query = (doctor: string) => (doctor ? `?doctor=${encodeURIComponent(doctor)}` : '')

export const chair = {
  get: (doctor: string, signal?: AbortSignal): Promise<ApiResult<ChairData>> =>
    api.get<ChairData>(`/chair${query(doctor)}`, signal ? { signal } : {}),
  /** Исход визита — тот же маршрут, что у журнала; ответ экрану не нужен:
      следом он перечитывает кресло. */
  status: (id: number, to: string) =>
    api.post<unknown>(`/schedule/appointments/${id}/status`, { to }),
}
