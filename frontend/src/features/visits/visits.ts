import { api } from '../../services/api'

/* Формы ответов — bot/app/modules/patients/api.py (`_visit_payload`).
   Графы дневника и шаблоны-заготовки — тексты сервера; можно ли писать
   (отменённый и неявившийся — нет) и какие позиции плана открыты для
   отметки (только активные) решает сервер. */

export interface VisitAppt {
  id: number
  when: string
  patient_id: number
  patient: string
  service: string
  doctor: string
  status: string
  status_label: string
  comment: string
  /** у услуги визита есть шаблон дневника клиники (10.11, «Din șablon») */
  tpl: boolean
}

export interface VisitRecord {
  acuze: string
  examen: string
  diagnostic: string
  tratament: string
  recomandari: string
  created: string
  updated: string
  author: string
}

export interface VisitField {
  id: string
  label: string
  rows: number
  placeholder: string
}

export interface VisitTemplate {
  id: string
  label: string
  values: Record<string, string>
}

export interface VisitPage {
  appt: VisitAppt
  record: VisitRecord | null
  editable: boolean
  note: string
  fields: VisitField[]
  templates: VisitTemplate[]
  plan: {
    linked: { id: number; text: string }[]
    /** `price` — MDL, 0 без цены: отметка проводит её в сольд (вопрос перед записью). */
    open: { id: number; text: string; in_lucru: boolean; price: number; tpl: boolean }[]
  }
  back: string
}

export interface VisitForm {
  acuze: string
  examen: string
  diagnostic: string
  tratament: string
  recomandari: string
  done: number[]
  back: string
}

export const visits = {
  get: (aid: number, back: string, signal?: AbortSignal) =>
    api.get<VisitPage>(`/visits/${aid}${back ? `?back=${encodeURIComponent(back)}` : ''}`,
      signal ? { signal } : {}),
  save: (aid: number, form: VisitForm) => api.post<VisitPage>(`/visits/${aid}`, form),
  /** «Din șablon» (10.11): тексты шаблонов услуги визита и отмеченных позиций
   *  с зубами и датой — правило сервера (`core/visit_tpl.compose`), ничего не пишет. */
  template: (aid: number, done: number[]) =>
    api.get<{ values: Record<string, string> }>(
      `/visits/${aid}/template${done.length ? `?done=${done.join(',')}` : ''}`),
}
