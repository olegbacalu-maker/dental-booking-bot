import { api, type ApiResult } from '../../services/api'

/** Что отдаёт GET /api/settings/clinic (bot/app/modules/settings/api.py). */
export interface ClinicSettings {
  name: string
  phone: string
  address: { ro: string; ru: string }
  /** Профиль ещё шаблонный (демо-данные) — экран показывает `hint`. */
  template: boolean
  /** Текст подсказки для шаблонного профиля — тот же, что в баннере каркаса. */
  hint: string
}

/** Что принимает POST — те же поля, что старая форма (part=clinic). */
export type ClinicForm = Pick<ClinicSettings, 'name' | 'phone' | 'address'>

/** Слой данных экрана: только адреса и типы, никакой логики. */
export const clinicSettings = {
  load: (signal?: AbortSignal): Promise<ApiResult<ClinicSettings>> =>
    api.get<ClinicSettings>('/settings/clinic', signal ? { signal } : {}),
  save: (form: ClinicForm): Promise<ApiResult<ClinicSettings>> =>
    api.post<ClinicSettings>('/settings/clinic', form),
}
