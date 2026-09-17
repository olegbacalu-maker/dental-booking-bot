import { api, type ApiResult } from '../../services/api'

/* Формы ответов — bot/app/modules/doctors/api.py. Цвета, инициалы, подписи
   состояний и часов приходят с сервера: клиент их не считает и не переводит. */

export interface DoctorStats {
  n: number
  pct: number
  noshow: number
}

export interface DoctorSummary {
  id: string
  name: string
  spec: string
  status: string
  room: string
  phone: string
  hours: string
  color: string
  initials: string
  photo: string
  archived: boolean
  stats: DoctorStats
}

export interface DoctorsList {
  doctors: DoctorSummary[]
  same_color: boolean
  /** Подписи состояний: activ / concediu / arhivat. */
  states: Record<string, string>
}

export interface WeekCell {
  date: string
  label: string
  dm: string
  count: number
  open: boolean
}

export interface TodayRow {
  id: number
  time: string
  patient: string
  patient_id: number | null
  phone: string
  service: string
  status: string
  status_label: string
  note: boolean
  comment: string
}

export interface ServiceRow {
  id: string
  name: string
  checked: boolean
  note: string
}

export interface DoctorCard {
  id: string
  name: string
  spec: string
  room: string
  phone: string
  email: string
  status: string
  color: string
  auto_color: boolean
  work_from: number | null
  work_to: number | null
  hours: { min: number; max: number }
  initials: string
  photo: string
  max_photo_mb: number
  future: number
  stats: DoctorStats
  warning: string
  week: WeekCell[]
  today: TodayRow[]
  services: ServiceRow[]
  states: Record<string, { label: string; hint: string }>
}

/** Что принимает POST /api/doctors/{dk} — те же поля, что старая форма. */
export interface DoctorProfile {
  name: string
  spec: string
  room: string
  phone: string
  email: string
  color: string
  auto_color: boolean
  work_from: number | null
  work_to: number | null
  status: string
}

export const doctors = {
  list: (signal?: AbortSignal): Promise<ApiResult<DoctorsList>> =>
    api.get<DoctorsList>('/doctors', signal ? { signal } : {}),
  add: (name: string, spec: string): Promise<ApiResult<{ id: string }>> =>
    api.post<{ id: string }>('/doctors', { name, spec }),
  resetColors: (): Promise<ApiResult<undefined>> => api.post<undefined>('/doctors/colors', {}),
  card: (dk: string, signal?: AbortSignal): Promise<ApiResult<DoctorCard>> =>
    api.get<DoctorCard>(`/doctors/${encodeURIComponent(dk)}`, signal ? { signal } : {}),
  save: (dk: string, profile: DoctorProfile): Promise<ApiResult<DoctorCard>> =>
    api.post<DoctorCard>(`/doctors/${encodeURIComponent(dk)}`, profile),
  setServices: (dk: string, ids: string[]): Promise<ApiResult<{ services: ServiceRow[] }>> =>
    api.post<{ services: ServiceRow[] }>(`/doctors/${encodeURIComponent(dk)}/services`, {
      services: ids,
    }),
  uploadPhoto: (dk: string, file: File): Promise<ApiResult<{ photo: string }>> => {
    const form = new FormData()
    form.append('file', file)
    return api.postForm<{ photo: string }>(`/doctors/${encodeURIComponent(dk)}/photo`, form)
  },
  deletePhoto: (dk: string): Promise<ApiResult<{ photo: string }>> =>
    api.post<{ photo: string }>(`/doctors/${encodeURIComponent(dk)}/photo/delete`, {}),
}
