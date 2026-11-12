import { api, type ApiResult } from '../../services/api'
import type { AddPreset } from '../schedule/AddDialog'
import type { NewAppt } from '../schedule/day'

/* Вкладка «Google Calendar»: формы ответов — bot/app/modules/schedule/gcal_api.py.
   Слова фильтров, причин и отказов — сервера; здесь только форма и адреса. */

export type GcalFilter = 'nou' | 'mutat' | 'omis' | 'nerecunoscut' | 'schimbat'

export interface GcalSource {
  id: number
  kind: string
  name: string
  loaded_at: string
  loaded_by: string
  service: string
}

export interface GcalPerson { id: number; name: string; phone: string }

export interface GcalRow {
  id: number
  /** Как в Google, без округления; пусто — событие без даты. */
  when: string
  date: string
  time: string
  minutes: number
  /** Только текстом; у перенесённой строки оба пусты. */
  title: string
  body: string
  series: boolean
  state: 'nou' | 'mutat' | 'omis' | 'nerecunoscut'
  changed: boolean
  gstatus: '' | 'cancelled' | 'gone'
  why: { code: string; text: string } | null
  round: { from: string; to: string } | null
  hint: {
    phone: string
    name: string
    doctor: { key: string; name: string } | null
    patients: GcalPerson[]
    exists: { appt_id: number; text: string } | null
  } | null
  /** Заполнение окна записи; час уже округлён сервером. */
  preset: {
    date: string; time: string; duration: string; doctor: string; service: string
    name: string; phone: string; nophone: boolean
  } | null
  appt: {
    id: number; pid: number; patient: string; doctor: string; when: string
    status: { code: string; text: string }; day_href: string
  } | null
  can: { move: boolean; link: boolean; skip: boolean; back: boolean }
}

export interface GcalLoad {
  new: number
  updated: number
  same: number
  changed: number
  gone: number
  unparsed: number
  skipped: number
  all_day: number
  cancelled: number
  past: number
  beyond: number
  refused: { name: string; code: string }[]
}

export interface GcalList {
  source: GcalSource | null
  f: GcalFilter
  q: string
  filters: { key: GcalFilter; label: string; n: number }[]
  days: { date: string; rows: GcalRow[] }[]
  undated: GcalRow[]
  total: number
  help: string[]
  keep_days: number
  horizon_days: number
  max_mb: number
  can: { clear: boolean }
  load?: GcalLoad
  appt_id?: number
}

const at = (f: string, q: string) => `?f=${encodeURIComponent(f)}&q=${encodeURIComponent(q)}`

export const gcalApi = {
  list: (f: string, q: string, signal?: AbortSignal): Promise<ApiResult<GcalList>> =>
    api.get<GcalList>(`/gcal${at(f, q)}`, signal ? { signal } : {}),
  file: (file: File, f: string, q: string) => {
    const form = new FormData()
    form.append('file', file)
    return api.postForm<GcalList>(`/gcal/file${at(f, q)}`, form)
  },
  move: (id: number, body: NewAppt & { pid?: number }, f: string, q: string) =>
    api.post<GcalList>(`/gcal/events/${id}/move${at(f, q)}`, body),
  skip: (id: number, on: boolean, f: string, q: string) =>
    api.post<GcalList>(`/gcal/events/${id}/skip${at(f, q)}`, { on }),
  link: (id: number, apptId: number, f: string, q: string) =>
    api.post<GcalList>(`/gcal/events/${id}/link${at(f, q)}`, { appt_id: apptId }),
  clear: () => api.post<GcalList>('/gcal/clear', {}),
}

/** Заполнение окна записи из строки. Пустой врач остаётся пустым: его
 *  выбирает человек. */
export function presetOf(r: GcalRow): AddPreset {
  const p = r.preset
  if (!p) return {}
  const minutes = Number(p.duration)
  return {
    ...(p.date ? { date: p.date } : {}),
    ...(p.time ? { time: p.time } : {}),
    ...(minutes > 0 ? { duration: minutes } : {}),
    doctor: p.doctor,
    ...(p.service ? { service: p.service } : {}),
    name: p.name,
    phone: p.phone,
  }
}

/** «HH:MM–HH:MM» события в том виде, в каком оно ляжет в журнал. */
export function spanOf(r: GcalRow): string {
  if (r.round) return r.round.to
  if (!r.time) return ''
  const [h, m] = r.time.split(':').map(Number)
  if (!r.minutes) return r.time
  const end = (h ?? 0) * 60 + (m ?? 0) + r.minutes
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${r.time}–${pad(Math.floor(end / 60) % 24)}:${pad(end % 60)}`
}

/** Минуты события после округления длины. */
export function minutesOf(r: GcalRow): number {
  return Number(r.preset?.duration) || r.minutes
}

const DAY = new Intl.DateTimeFormat('ro-RO', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

/** «luni, 16 noiembrie 2026» из голой даты; полдень — мимо перехода времени. */
export function dayTitle(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  return DAY.format(new Date(y, m - 1, d, 12))
}

/** «16.11 09:10» из «2026-11-16T09:10». */
export function shortWhen(when: string): string {
  const [date = '', time = ''] = when.split('T')
  const [, m = '', d = ''] = date.split('-')
  return `${d}.${m} ${time}`.trim()
}
