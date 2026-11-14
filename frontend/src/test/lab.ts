import type { ApiResult } from '../services/api'
import type { FormData, Lab, ListData, Order, OrderRow, PatientData, SettingsData, Words } from '../features/lab/lab'

/* Ответы сервера для проверок клиента — формы контракта `lab-contract.md`. */

export const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

export const CAN = { money: true, labs: true, settings: true }
export const CAN_DOC = { money: false, labs: false, settings: false }

export const row = (p: Partial<OrderRow> = {}): OrderRow => ({
  id: 1, nr: 41, pid: 2, patient: 'Ion Popescu', fisa: '0002', doctor_id: 'er', doctor: 'Dr. Elena Rusu',
  lab_id: 1, lab: 'Dental Lab Prim', status: 'trimis', status_label: 'Trimis la laborator', stage: 1,
  sent_on: '2026-11-05', due_on: '2026-11-12', received_on: '', done_on: '', urgent: false, impression: '',
  work: 'Coroană', teeth: [26], late: true, days_late: 2, due_in: -2, ready: false, next_appt: null, visit_wait: false,
  total_bani: 180000, steps: [{ act: 'gata', label: 'E gata', main: true }, { act: 'primit', label: 'Primit', main: false }],
  ...p,
})

export const LABS = [
  { id: 1, name: 'Dental Lab Prim', days: 7, workdays: '12345', active: true },
  { id: 2, name: 'ArtDent Laborator', days: 5, workdays: '123456', active: true },
]

export const list = (orders: OrderRow[], p: Partial<ListData> = {}): ListData => ({
  today: '2026-11-14', f: 'lucru', orders, labs: LABS, can: CAN,
  counts: { lucru: orders.length, intarziate: orders.filter((o) => o.late).length, ridicat: 0, primite: 0, vizita: orders.filter((o) => o.visit_wait).length,
    finalizate: 0, anulate: 0, toate: orders.length },
  ...p,
})

export const WORDS: Words = {
  status: { trimis: 'Trimis la laborator' },
  kind: { trimis: 'Trimis la laborator' },
  cause: { culoare: 'Culoare', adaptare: 'Adaptare / prindere', ocluzie: 'Ocluzie', fractura: 'Fractură / ciob', alta: 'Altă cauză' },
  payer: { laborator: 'Laboratorul (garanție)', clinica: 'Clinica', pacient: 'Pacientul' },
  impression: { '': '—', amprenta: 'Amprentă', scanare: 'Scanare intraorală', model: 'Model' },
}

export const form = (p: Partial<FormData> = {}): FormData => ({
  today: '2026-11-14',
  patient: { pid: 2, name: 'Ion Popescu', fisa: '0002' },
  plan: [
    { id: 3, tooth: 26, procedure: 'Coroană metalo-ceramică', doctor: 'Dr. Elena Rusu', doctor_id: 'er', status: 'in_lucru', ordered: null },
    { id: 5, tooth: 45, procedure: 'Punte zirconiu 44–46', doctor: 'Dr. Elena Rusu', doctor_id: 'er', status: 'in_lucru', ordered: null },
  ],
  labs: LABS, doctors: [{ id: 'er', name: 'Dr. Elena Rusu' }, { id: 'im', name: 'Dr. Ion Munteanu' }], doctor_id: 'er',
  words: WORDS, works: ['Coroană', 'Punte'], materials: ['Zirconiu', 'Metalo-ceramică'], shades: ['A1', 'A2', 'A3'], who: 'name',
  last_prices: [{ lab_id: 1, work: 'coroană', price_bani: 180000, nr: 41, on: '2026-11-05' }],
  can: CAN,
  ...p,
})

export const order = (p: Partial<Order> = {}): Order => ({
  ...row({ status: 'proba', status_label: 'La probă', late: false, due_in: null }),
  appointment_id: null, note: 'Umăr ceramic', data: {},
  items: [{ id: 11, plan_item_id: 3, plan: { id: 3, procedure: 'Coroană metalo-ceramică', tooth: 26, status: 'in_lucru' },
    work: 'Coroană', material: 'Metalo-ceramică', shade: 'A2', teeth: [26], qty: 1, grp: null, price_bani: 180000 }],
  events: [
    { id: 1, kind: 'trimis', kind_label: 'Trimis la laborator', on_date: '2026-11-05', due_on: '2026-11-12', cause: null, cause_label: '',
      payer: null, payer_label: '', note: '', actor: 'Director', doer: '', at: '2026-11-05T08:00:00Z', undone: false },
  ],
  ...p,
})

export const patient = (orders: OrderRow[], p: Partial<PatientData> = {}): PatientData => ({
  today: '2026-11-14', pid: 2, orders, next_appt: null, can: CAN,
  plan: Object.fromEntries(orders.filter((o) => o.status !== 'anulat').map((o) => [String(3), {
    order_id: o.id, nr: o.nr, status: o.status, status_label: o.status_label, due_on: o.due_on, late: o.late, ready: o.ready }])),
  ...p,
})

export const lab = (p: Partial<Lab> = {}): Lab => ({
  id: 1, name: 'Dental Lab Prim', phone: '022 123 456', email: 'comenzi@labprim.md', contact: 'Andrei', days: 7, workdays: '12345',
  active: true, sort: 0, data: {}, orders: 4, open: 2, ...p,
})

export const settings = (labs: Lab[], p: Partial<SettingsData> = {}): SettingsData => ({
  labs, prefs: { who: 'name', late_gata: false }, can: CAN, ...p,
})
