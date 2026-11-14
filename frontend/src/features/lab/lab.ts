import { api, type ApiResult } from '../../services/api'

/* Формы ответов — сервер раздела (`/api/lab*`, `/api/settings/lab*`). Слова
   статусов, событий и кнопок, сроки, опоздание и ближайший визит приходят
   готовыми: экран своих правил переходов и дат не держит. Цен без права на
   деньги в ответе нет вовсе — поэтому они необязательные. */

export type Status = 'trimis' | 'gata' | 'primit' | 'proba' | 'finalizat' | 'anulat'
export type Act = 'gata' | 'primit' | 'proba' | 'finalizat' | 'etapa' | 'refacere' | 'undo' | 'cancel'
export type Impression = '' | 'amprenta' | 'scanare' | 'model'
export type Filter = 'lucru' | 'intarziate' | 'ridicat' | 'primite' | 'vizita' | 'finalizate' | 'anulate' | 'toate'

export interface Can { money: boolean; labs: boolean; settings: boolean }

export interface NextAppt { id: number; starts_at: string; date: string; time: string; doctor: string; day: 'azi' | 'maine' | null }

export interface Step { act: Act; label: string; main: boolean }

export interface OrderRow {
  id: number
  nr: number
  pid: number
  patient: string
  fisa: string
  doctor_id: string
  doctor: string
  lab_id: number | null
  lab: string
  status: Status
  status_label: string
  stage: number
  sent_on: string
  due_on: string
  received_on: string
  done_on: string
  urgent: boolean
  impression: Impression
  /** Сводка строк: «Coroană ×2 · Fațetă». */
  work: string
  teeth: number[]
  late: boolean
  days_late: number | null
  due_in: number | null
  ready: boolean
  next_appt: NextAppt | null
  /** Визит сегодня или завтра, а работа ещё не в клинике. */
  visit_wait: boolean
  total_bani?: number
  /** Кнопки строки — если сервер их прислал; иначе шаги только в окне заказа. */
  steps?: Step[]
}

export interface LabBrief { id: number; name: string; days: number; workdays: string; active: boolean }

export interface ListData {
  today: string
  f: Filter
  counts: Record<Filter, number>
  orders: OrderRow[]
  labs: LabBrief[]
  can: Can
}

export interface PlanBadge { order_id: number; nr: number; status: Status; status_label: string; due_on: string; late: boolean; ready: boolean }

export interface PatientData {
  today: string
  pid: number
  orders: OrderRow[]
  plan: Record<string, PlanBadge>
  next_appt: NextAppt | null
  can: Can
}

export interface FormPlan { id: number; tooth: number | null; procedure: string; doctor: string; doctor_id: string | null; status: string; ordered: PlanBadge | null }

export interface Words {
  status: Record<string, string>
  kind: Record<string, string>
  cause: Record<string, string>
  payer: Record<string, string>
  impression: Record<string, string>
}

export interface LastPrice { lab_id: number; work: string; price_bani: number; nr: number; on: string }

export interface FormData {
  today: string
  patient: { pid: number; name: string; fisa: string } | null
  plan: FormPlan[]
  labs: LabBrief[]
  doctors: { id: string; name: string }[]
  doctor_id: string
  words: Words
  works: string[]
  materials: string[]
  shades: string[]
  who: 'name' | 'fisa'
  last_prices?: LastPrice[]
  can: Can
}

export interface Item {
  id?: number
  plan_item_id: number | null
  plan?: { id: number; procedure: string; tooth: number | null; status: string } | null
  work: string
  material: string
  shade: string
  teeth: number[]
  qty: number
  grp: number | null
  price_bani?: number | null
}

export interface Event {
  id: number
  kind: string
  kind_label: string
  on_date: string
  due_on: string | null
  cause: string | null
  cause_label: string
  payer: string | null
  payer_label: string
  note: string
  actor: string
  doer: string
  at: string
  undone: boolean
}

export interface Order extends OrderRow {
  appointment_id: number | null
  note: string
  data: { tech?: string; invoice?: string }
  items: Item[]
  events: Event[]
}

export interface OrderData { order: Order; steps: Step[]; can: Can }

export interface OrderBody {
  lab_id: number | null
  lab_name: string
  doctor_id: string
  sent_on: string
  due_on: string
  urgent: boolean
  impression: Impression
  note: string
  items: Item[]
}

export interface Lab extends LabBrief {
  phone: string
  email: string
  contact: string
  sort: number
  data: { idno?: string; legal?: string; address?: string; own?: boolean; note?: string }
  orders: number
  open: number
}

export interface Prefs { who: 'name' | 'fisa'; late_gata: boolean }
export interface SettingsData { labs: Lab[]; prefs: Prefs; can: Can }

export interface DashRow { id: number; nr: number; pid: number; patient: string; work: string; lab: string; due_on: string; days_late: number | null; next_appt: NextAppt | null }
export interface DashData { late: DashRow[]; ready: DashRow[]; visit: DashRow[]; counts: { late: number; ready: number; visit: number } }

const opt = (signal?: AbortSignal) => (signal ? { signal } : {})

export const labApi = {
  list: (q: { f: Filter; lab: number; q: string }, signal?: AbortSignal): Promise<ApiResult<ListData>> => {
    const p = new URLSearchParams()
    if (q.f !== 'lucru') p.set('f', q.f)
    if (q.lab) p.set('lab', String(q.lab))
    if (q.q) p.set('q', q.q)
    const s = p.toString()
    return api.get<ListData>(`/lab${s ? `?${s}` : ''}`, opt(signal))
  },
  patient: (pid: number, signal?: AbortSignal) => api.get<PatientData>(`/lab/patient/${pid}`, opt(signal)),
  form: (pid: number | null, planItem: number | null, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (pid) p.set('pid', String(pid))
    if (planItem) p.set('plan_item', String(planItem))
    return api.get<FormData>(`/lab/form?${p.toString()}`, opt(signal))
  },
  due: (lab: number, sent: string, signal?: AbortSignal) => api.get<{ due_on: string }>(`/lab/due?lab=${lab}&sent=${sent}`, opt(signal)),
  order: (id: number, signal?: AbortSignal) => api.get<OrderData>(`/lab/order/${id}`, opt(signal)),
  create: (b: OrderBody & { pid: number }) => api.post<{ id: number; nr: number }>('/lab/order', b),
  save: (id: number, b: OrderBody) => api.post<null>(`/lab/order/${id}`, b),
  step: (id: number, to: 'gata' | 'primit' | 'proba' | 'finalizat', note = '') => api.post<null>(`/lab/order/${id}/step`, { to, note }),
  etapa: (id: number, b: { due_on: string; note: string }) => api.post<null>(`/lab/order/${id}/etapa`, b),
  refacere: (id: number, b: { cause: string; payer: string; due_on: string; note: string }) => api.post<null>(`/lab/order/${id}/refacere`, b),
  undo: (id: number) => api.post<null>(`/lab/order/${id}/undo`, {}),
  cancel: (id: number, why: string) => api.post<null>(`/lab/order/${id}/cancel`, { why }),
  settings: (signal?: AbortSignal) => api.get<SettingsData>('/settings/lab', opt(signal)),
  saveLab: (b: Partial<Lab> & { name: string }) => api.post<{ id: number }>('/settings/lab/item', b),
  dropLab: (id: number) => api.post<null>(`/settings/lab/item/${id}/delete`, {}),
  prefs: (b: Partial<Prefs>) => api.post<null>('/settings/lab/prefs', b),
}

/** Лист наряда — документ сервера, не экран. */
export const sheetUrl = (id: number, back: string) => `/admin/lab/${id}/tipar?back=${encodeURIComponent(back)}`

export const WEEKDAYS: [string, string][] = [['1', 'Lu'], ['2', 'Ma'], ['3', 'Mi'], ['4', 'Jo'], ['5', 'Vi'], ['6', 'Sâ'], ['7', 'Du']]
export const COMENZI = { one: '1 comandă', few: '{n} comenzi', many: '{n} de comenzi' }
export const LUCRARI = { one: '1 lucrare', few: '{n} lucrări', many: '{n} de lucrări' }

/** Работа и материал — из слов позиции плана: врач уже написал «Coroană zirconiu». */
export function guess(procedure: string): { work: string; material: string } {
  const p = procedure.toLowerCase()
  const has = (...w: string[]) => w.some((x) => p.includes(x))
  const work = has('implant') && has('coroan') ? 'Coroană pe implant'
    : has('punte') ? 'Punte'
      : has('fațet', 'fatet') ? 'Fațetă'
        : has('inlay', 'onlay') ? 'Inlay / onlay'
          : has('schelet') ? 'Proteză scheletată'
            : has('proteză totală', 'proteza totala') ? 'Proteză totală'
              : has('protez') ? 'Proteză parțială'
                : has('align', 'gutier') ? 'Alignere / gutiere'
                  : has('provizor') ? 'Lucrare provizorie'
                    : has('coroan') ? 'Coroană' : ''
  const material = has('zircon') ? 'Zirconiu'
    : has('metalo') ? 'Metalo-ceramică'
      : has('e.max', 'emax') ? 'E.max (disilicat de litiu)'
        : has('schelet') ? 'CoCr (scheletat)'
          : has('align', 'gutier') ? 'Polimer termoformat'
            : has('ceramic') ? 'E.max (disilicat de litiu)' : ''
  return { work, material }
}

/** Похожа ли позиция плана на работу техника — тогда у неё кнопка заказа. */
export const isLabWork = (procedure: string): boolean => guess(procedure).work !== ''

/** Зубы из слов позиции: «Punte 44–46» → 44, 45, 46 (в пределах одного квадранта). */
export function teethOf(tooth: number | null, procedure: string): number[] {
  const m = procedure.match(/\b([1-4][1-8])\s*[–-]\s*([1-4][1-8])\b/)
  if (m) {
    const a = Number(m[1])
    const b = Number(m[2])
    if (Math.floor(a / 10) === Math.floor(b / 10)) {
      const out: number[] = []
      for (let n = Math.min(a, b); n <= Math.max(a, b); n++) out.push(n)
      return out
    }
  }
  return tooth ? [tooth] : []
}

export const isOpen = (o: { status: Status }): boolean => o.status !== 'finalizat' && o.status !== 'anulat'

/** Бани → «1 800» (копейки — только если они есть). */
export function money(bani: number | null | undefined): string {
  if (bani == null) return '—'
  const lei = bani / 100
  return lei.toLocaleString('ro-RO', { minimumFractionDigits: Number.isInteger(lei) ? 0 : 2, maximumFractionDigits: 2 })
}

/** «2026-11-18» → «18.11». */
export function dm(iso: string | null | undefined): string {
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(iso ?? '')
  return m ? `${m[2]}.${m[1]}` : '—'
}
export function dmy(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? '')
  return m ? `${m[3]}.${m[2]}.${m[1]}` : '—'
}
