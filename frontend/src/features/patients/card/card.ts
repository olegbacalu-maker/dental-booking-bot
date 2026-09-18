import { api, type ApiResult } from '../../../services/api'

/* Формы ответов — bot/app/modules/patients/api.py (`_card`). Все расчёты
   фиши (суммы плана, прогресс, долг, «следующий»/«последний» визит, пилюли,
   риски анамнеза, чем открывать документ) сделаны на сервере в card.py —
   те же, что у старой страницы; клиент их не повторяет. Даты уже в поясе
   клиники и в виде, в каком их читает стойка. Удача действия возвращает
   свежую фишу целиком. */

export interface Pill {
  tone: string
  icon: string
  text: string
}

export interface Profile {
  name: string
  phone: string
  birth_date: string
  /** Дата рождения человеку (dd.mm.yyyy) или год у пациента из бота. */
  birth: string
  gender: string
  gender_label: string
  idnp: string
  email: string
  address: string
  insurance: string
  primary_doctor: string
  file_no: string
  notes: string
  lang: string
  age: number | null
  channel: string
  /** Дата заведения фиши dd.mm.yyyy и её год. */
  created: string
  year: string
}

export interface Hero {
  pills: Pill[]
  last: { date: string; service: string } | null
  next: { date: string; time: string; service: string; doctor: string } | null
  days_ago: number | null
}

export interface Kpi {
  visits: number
  active: number
  done: number
  canc: number
}

export interface Alert {
  id: number
  kind: string
  label: string
  icon: string
  text: string
}

export interface Anamneza {
  filled: boolean
  state: 'none' | 'ok' | 'risk'
  n_risk: number
  flags: string[]
  texts: Record<string, string>
  marked: string[]
  free: { label: string; text: string }[]
  when: string
  author: string
}

export interface PlanItem {
  id: number
  tooth: number | null
  procedure: string
  doctor: string
  status: string
  label: string
  price: number | null
  due: string
  overdue: boolean
  done: string
  motiv: string
  /** Куда ведёт кнопка следующего шага (ребро PLAN_EDGES). */
  next: string
  refusable: boolean
  deletable: boolean
}

export interface Plan {
  items: PlanItem[]
  counts: Record<string, number>
  n_act: number
  default_tab: string
  total: number
  total_done: number
  n_track: number
  pct_done: number
}

export interface Payment {
  id: number
  when: string
  method: string
  icon: string
  amount: number
  neg: boolean
  note: string
  taken_by: string
}

export interface Finance {
  charged: number
  paid: number
  debt: number
  sold: { kind: 'bad' | 'plus' | 'ok'; amount: number } | null
  payments: Payment[]
  can_delete: boolean
}

export interface Doc {
  id: number
  filename: string
  when: string
  size: string
  mime: string
  category: string
  icon: string
  view: 'img' | 'pdf' | 'ext'
}

export interface Visit {
  id: number
  when: string
  status: string
  status_label: string
  service: string
  doctor: string
  is_next: boolean
  consult: 'rec' | 'invite' | ''
  diag: string
  url: string
}

export interface ActivityItem {
  id: number
  kind: string
  icon: string
  text: string
  when: string
  hhmm: string
  who: string
}

export interface Activity {
  items: ActivityItem[]
  shown: number
  views: boolean
}

export interface Appoint {
  services: { id: string; label: string }[]
  doctors: Record<string, string[]>
  names: Record<string, string>
  primary: string
  today: string
}

export interface Options {
  alert_kinds: { id: string; label: string }[]
  anamneza_flags: { id: string; label: string }[]
  anamneza_texts: { id: string; label: string; placeholder: string }[]
  doc_categories: { id: string; label: string }[]
  max_doc_mb: number
  pay_methods: { id: string; icon: string }[]
  plan_labels: Record<string, string>
  tab_states: Record<string, string[]>
  teeth: number[]
  milk: number[]
  doctors: string[]
}

export interface PatientCard {
  id: number
  name: string
  initials: string
  archived: boolean
  erasure: 'delete' | 'anon'
  profile: Profile
  hero: Hero
  kpi: Kpi
  alerts: Alert[]
  anamneza: Anamneza
  plan: Plan
  finance: Finance
  documents: Doc[]
  visits: { history: Visit[]; live: Visit[]; n_total: number }
  activity: Activity
  appoint: Appoint
  options: Options
}

export interface ProfileForm {
  name: string
  phone: string
  birth_date: string
  gender: string
  idnp: string
  email: string
  address: string
  insurance: string
  primary_doctor: string
  file_no: string
  notes: string
  lang: string
}

export interface PlanForm {
  tooth: string
  procedure: string
  doctor: string
  price: string
  due_date: string
}

export interface AppointForm {
  date: string
  time: string
  doctor: string
  service: string
}

/** Ответ стирания: фиши больше нет (адрес списка) или она обезличена. */
export type EraseResult = PatientCard | { url: string }

/** 1200 → «1 200»: тысячи пробелом, как всюду в фише. */
export function mdl(n: number): string {
  return String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

const P = (pid: number) => `/patients/${pid}`
/* Действие несёт тот же ?views=1, что открытая фиша: свежая фиша в ответе
   приходит в том же режиме ленты (с просмотрами или без). */
const V = (views: boolean) => (views ? '?views=1' : '')

export const patientCard = {
  get: (pid: number, views: boolean, signal?: AbortSignal) =>
    api.get<PatientCard>(`${P(pid)}${V(views)}`, signal ? { signal } : {}),
  teeth: (pid: number, signal?: AbortSignal) =>
    api.get<{ html: string }>(`${P(pid)}/teeth`, signal ? { signal } : {}),
  activity: (pid: number, views: boolean) =>
    api.get<Activity>(`${P(pid)}/activity${V(views)}`),
  saveProfile: (pid: number, views: boolean, form: ProfileForm) =>
    api.post<PatientCard>(`${P(pid)}/profile${V(views)}`, form),
  archive: (pid: number, views: boolean, on: boolean) =>
    api.post<PatientCard>(`${P(pid)}/archive${V(views)}`, { on }),
  erase: (pid: number, views: boolean, confirm: string) =>
    api.post<EraseResult>(`${P(pid)}/erase${V(views)}`, { confirm }),
  addAlert: (pid: number, views: boolean, kind: string, text: string) =>
    api.post<PatientCard>(`${P(pid)}/alerts${V(views)}`, { kind, text }),
  delAlert: (pid: number, views: boolean, aid: number) =>
    api.post<PatientCard>(`${P(pid)}/alerts/${aid}/delete${V(views)}`, {}),
  saveAnamneza: (pid: number, views: boolean, flags: string[], texts: Record<string, string>) =>
    api.post<PatientCard>(`${P(pid)}/anamneza${V(views)}`, { flags, ...texts }),
  addPlan: (pid: number, views: boolean, form: PlanForm) =>
    api.post<PatientCard>(`${P(pid)}/plan${V(views)}`, form),
  planStatus: (pid: number, views: boolean, iid: number, to: string, motiv = '') =>
    api.post<PatientCard>(`${P(pid)}/plan/${iid}/status${V(views)}`, { to, motiv }),
  delPlan: (pid: number, views: boolean, iid: number) =>
    api.post<PatientCard>(`${P(pid)}/plan/${iid}/delete${V(views)}`, {}),
  addPayment: (pid: number, views: boolean, amount: string, method: string, note: string) =>
    api.post<PatientCard>(`${P(pid)}/payments${V(views)}`, { amount, method, note }),
  delPayment: (pid: number, views: boolean, payId: number) =>
    api.post<PatientCard>(`${P(pid)}/payments/${payId}/delete${V(views)}`, {}),
  uploadDoc: (pid: number, views: boolean, file: File, category: string) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    fd.append('category', category)
    return api.postForm<PatientCard>(`${P(pid)}/documents${V(views)}`, fd)
  },
  delDoc: (pid: number, views: boolean, docId: number) =>
    api.post<PatientCard>(`${P(pid)}/documents/${docId}/delete${V(views)}`, {}),
  openDoc: (docId: number) =>
    api.post<{ opened: boolean; reason: string }>(`/documents/${docId}/open`, {}),
  slots: (pid: number, date: string, doctor: string, service: string, signal?: AbortSignal) =>
    api.get<{ slots: string[] }>(
      `${P(pid)}/slots?date=${encodeURIComponent(date)}&doctor=${encodeURIComponent(doctor)}` +
        `&service=${encodeURIComponent(service)}`,
      signal ? { signal } : {},
    ),
  appoint: (pid: number, views: boolean, form: AppointForm) =>
    api.post<PatientCard>(`${P(pid)}/appoint${V(views)}`, form),
}

export type CardResult = ApiResult<PatientCard>
