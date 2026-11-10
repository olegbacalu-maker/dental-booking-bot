import { api, type ApiResult } from '../../services/api'

/* «Registre» (10.11.2026): формы ответов — bot/app/modules/registre/api.py,
   правила — bot/app/core/registre.py. КТО СДЕЛАЛ — человек из окна (`doer`,
   каталог «Personal»; registre-people 10.11); учётку, внёсшую запись, и
   время ставит СЕРВЕР: клиент их не присылает. Тексты ответов — сервера
   (MSG_BANNER); здесь только формы и адреса. */

export type RegKey = '257' | '502' | '501'
export type Test = '' | 'ok' | 'fail'
export type Bio = '' | 'wait' | 'ok' | 'fail'

export interface Art { name: string; qty: number; pack: string }
export interface Program { label: string; temp: string; pressure: string; min: number }

interface RowBase {
  id: number
  reg: RegKey
  /** Учётка, внёсшая запись. */
  actor: string
  /** Кто сделал — человек из окна; у строк до 10.11 (`legacy`) — та же учётка. */
  doer: string
  legacy: boolean
  /** «dd.mm.yyyy HH:MM» — время программы, когда строка записана. */
  at: string
  fixes: number | null
  fixed_by: number | null
  why: string
}

export interface CycleRow extends RowBase {
  date: string; start: string; end: string; open: boolean; ster_id: number | null; ster: string
  program: string; pressure: string; temp: string; arts: Art[]; chem: Test; term: Test; bio: Bio
  end_actor: string; end_doer: string; bio_actor: string; bio_at: string
  /** UTC ISO — минуты идущего цикла считает браузер. */
  started_at: string
}

export interface CleanRow extends RowBase {
  room_id: number | null; room: string; plan: string; done: string; solution: string
  /** `sup_actor` — кто проверил (человек), `sup_by` — учётка; пусто у проверок до 10.11. */
  sup_actor: string; sup_by: string; sup_at: string; actor_id: string
}

export interface UvRow extends RowBase {
  date: string; lamp_id: number | null; lamp: string; room: string; cond: string; on: string; off: string
  open: boolean; minutes: number | null; rest: number | null; off_actor: string; on_at: string
}

export interface Item {
  id: number
  kind: 'ster' | 'lamp' | 'room' | 'solution' | 'article' | 'pack' | 'staff'
  name: string
  nr: string
  room: string
  active: boolean
  data: {
    type?: 'abur' | 'aer'
    programs?: Program[]
    m3?: number; hours?: number; base?: number; since?: string; screened?: boolean
    changes?: { date: string; actor: string }[]
    every?: number
    /** «Personal»: должность и «verifică curățenia». */
    func?: string; sup?: boolean
  }
}

export interface Lamp extends Item { used: number; rest: number; low: boolean }

export interface RegData {
  /** ISO-дата «сегодня» программы; `month` — «YYYY-MM» истории. */
  today: string
  month: string
  prev: string
  next: string
  me: { name: string; id: string }
  can: { delete: boolean; settings: boolean }
  sters: (Item & { running: CycleRow | null; last: CycleRow | null })[]
  lamps: (Lamp & { on: UvRow | null })[]
  rooms: (Item & { next: string; last: string; due: boolean; late: boolean; done_azi: boolean; done_ieri: boolean })[]
  waiting: CleanRow[]
  /** «Personal pentru registre» — включённые люди каталога. */
  staff: Person[]
  solutions: string[]
  articles: string[]
  packs: string[]
  /** Каталог пуст — экран ведёт в настройки. */
  empty: boolean
  feed: (CycleRow | CleanRow | UvRow)[]
  rows: { '257': CycleRow[]; '502': CleanRow[]; '501': UvRow[] }
}

export interface Person { name: string; func: string; sup: boolean }

export interface Catalog {
  items: { ster: Item[]; lamp: Lamp[]; room: Item[]; solution: Item[]; article: Item[]; pack: Item[]; staff: Item[] }
  norms: { id: number | null; text: string }
}

const R = '/registre'
export const regApi = {
  get: (month: string, signal?: AbortSignal): Promise<ApiResult<RegData>> =>
    api.get<RegData>(`${R}${month ? `?month=${encodeURIComponent(month)}` : ''}`, signal ? { signal } : {}),
  start: (b: { ster_id: number; program: number; arts: Art[]; doer: string; temp?: string; pressure?: string }) =>
    api.post<null>(`${R}/257`, b),
  finish: (id: number, b: { chem: Test; term: Test; bio: Bio; doer: string }) => api.post<null>(`${R}/257/${id}/finish`, b),
  bio: (id: number, bio: 'ok' | 'fail') => api.post<null>(`${R}/257/${id}/bio`, { bio }),
  clean: (b: { room_id: number; solution: string; doer: string; day: 'azi' | 'ieri' }) => api.post<null>(`${R}/502`, b),
  sup: (id: number, who: string) => api.post<null>(`${R}/502/${id}/sup`, { who }),
  uvOn: (b: { lamp_id: number; cond: 'fara' | 'prezenta'; doer: string }) => api.post<null>(`${R}/501`, b),
  uvOff: (id: number) => api.post<null>(`${R}/501/${id}/off`, {}),
  fix: (reg: RegKey, id: number, b: Record<string, unknown>) => api.post<null>(`${R}/${reg}/${id}/fix`, b),
  del: (reg: RegKey, id: number) => api.post<null>(`${R}/${reg}/${id}/delete`, {}),
}

export const catApi = {
  get: (signal?: AbortSignal) => api.get<Catalog>('/settings/registre', signal ? { signal } : {}),
  save: (b: Record<string, unknown>) => api.post<{ id: number }>('/settings/registre/item', b),
  lampNew: (id: number) => api.post<null>(`/settings/registre/lamp/${id}/new`, {}),
}

/** Адреса документа (лист и Excel) — не экраны: открываются документом. */
export const printUrl = (reg: RegKey, month: string) => `/admin/registre/tipar/${reg}?month=${month}`
export const excelUrl = (reg: RegKey, month: string) => `/admin/registre/excel/${reg}?month=${month}`

/** Минуты с момента `iso` до `now` — для идущего цикла и включённой лампы. */
export function minutesSince(iso: string, now: number): number {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? Math.max(0, Math.floor((now - t) / 60000)) : 0
}

/** «3 h 42 min» / «12 min». */
export function dur(min: number): string {
  const h = Math.floor(min / 60)
  return h ? `${h} h ${min % 60} min` : `${min} min`
}

const MONTHS = ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie', 'iulie', 'august',
  'septembrie', 'octombrie', 'noiembrie', 'decembrie']

/** «2026-11» → «Noiembrie 2026»; «2026-11-10» → «10 noiembrie». */
export function monthLabel(m: string): string {
  const [y, mm] = m.split('-').map(Number)
  const w = MONTHS[(mm ?? 1) - 1] ?? ''
  return `${w.charAt(0).toUpperCase()}${w.slice(1)} ${y}`
}
export function dayLabel(iso: string): string {
  const [, mm, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[(mm ?? 1) - 1] ?? ''}`
}

/** «2026-03-01» → «01.03.2026»; не дата — как есть. */
export function dmy(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso
}
