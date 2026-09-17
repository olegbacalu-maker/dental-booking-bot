import { api, type ApiResult } from '../../services/api'

/* Формы ответов — bot/app/modules/patients/api.py. Даты уже в поясе клиники и
   в виде, в каком их читает стойка; статус, врач и инициалы выведены на
   сервере той же функцией, что рисует старая страница. Отбор, порядок и
   страницу считает база (db.patients_rows) — клиент шлёт только параметры. */

export interface PatientRow {
  id: number
  name: string
  initials: string
  phone: string
  email: string
  channel: string
  birth: string
  age: number | null
  doctor: string
  /** Врач из фиши (true) или выведенный из последнего визита (false). */
  doctor_own: boolean
  last: string
  next: string
  n_visits: number
  /** Долг в MDL; минус — аванс. */
  debt: number
  status: string
  archived: boolean
}

export interface PatientsPage {
  rows: PatientRow[]
  total: number
  page: number
  pages: number
  per: number
  sort: string
  /** Сколько архивных спрятано этим отбором (0, когда их спросили явно). */
  hidden_arh: number
  n_arh: number
}

export interface Tile {
  icon: string
  tone: string
  value: string
  /** Подпись под числом — кусок серверной прозы (тренд со стрелкой). */
  foot: string
  href: string
}

export interface PatientsSummary {
  tiles: Tile[]
  doctors: string[]
  channels: { id: string; label: string }[]
  statuses: { id: string; label: string; cls: string }[]
  per: number[]
  clinic_doctors: string[]
}

export interface NewPatient {
  name: string
  phone: string
  birth_date: string
  email: string
  primary_doctor: string
}

/** Отбор списка — те же имена, что у адреса старой страницы (?q=&med=&st=…). */
export interface Filters {
  q: string
  med: string
  st: string
  ch: string
  dat: string
  sort: string
  page: number
  per: number
}

export const SORTS = ['last', 'name', 'new', 'debt'] as const
const PERS = [10, 20, 50]

export const DEFAULT_FILTERS: Filters = {
  q: '', med: '', st: '', ch: '', dat: '', sort: 'last', page: 1, per: 20,
}

/** Отбор из параметров узла (адрес принадлежит серверу — он их и кладёт). */
export function filtersFromParams(p: Record<string, string>): Filters {
  const per = Number(p.per)
  const page = Number(p.page)
  const sort = p.sort ?? ''
  return {
    q: (p.q ?? '').slice(0, 60),
    med: p.med ?? '',
    st: p.st ?? '',
    ch: p.ch ?? '',
    dat: p.dat ?? '',
    sort: (SORTS as readonly string[]).includes(sort) ? sort : 'last',
    page: Number.isInteger(page) && page > 0 ? page : 1,
    per: PERS.includes(per) ? per : 20,
  }
}

/** Строка запроса без значений по умолчанию — как `url()` старой страницы. */
export function filtersToQuery(f: Filters, withPage = true): string {
  const u = new URLSearchParams()
  if (f.q) u.set('q', f.q)
  if (f.med) u.set('med', f.med)
  if (f.st) u.set('st', f.st)
  if (f.ch) u.set('ch', f.ch)
  if (f.dat) u.set('dat', f.dat)
  if (f.sort !== 'last') u.set('sort', f.sort)
  if (f.per !== 20) u.set('per', String(f.per))
  if (withPage && f.page > 1) u.set('page', String(f.page))
  const s = u.toString()
  return s ? `?${s}` : ''
}

export function sameFilters(a: Filters, b: Filters): boolean {
  return (Object.keys(a) as (keyof Filters)[]).every((k) => a[k] === b[k])
}

/** Есть ли отбор помимо порядка и размера страницы (для «Resetează» и пустого вида). */
export function isDirty(f: Filters): boolean {
  return Boolean(f.q || f.med || f.st || f.ch || f.dat)
}

export const patients = {
  page: (f: Filters, signal?: AbortSignal): Promise<ApiResult<PatientsPage>> =>
    api.get<PatientsPage>(`/patients${filtersToQuery(f)}`, signal ? { signal } : {}),
  summary: (signal?: AbortSignal) =>
    api.get<PatientsSummary>('/patients/summary', signal ? { signal } : {}),
  peek: (id: number) => api.get<{ html: string }>(`/patients/${id}/peek`),
  create: (form: NewPatient) => api.post<{ id: number; url: string }>('/patients', form),
}
