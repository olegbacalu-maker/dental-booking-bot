import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../../services/api'
import { ApiError } from '../../../types/api'
import type { PatientCard } from './card'
import { mdl } from './card'
import { PatientCardScreen } from './PatientCardScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

/* модель одонтограммы — минимальная: один зуб в каждой дуге, без мостов */
const TOOTH = (n: number, jaw: 'sus' | 'jos') => ({
  jaw, mez: 'right' as const, state: 'ok', note: '', doctor: '', at: '', sf: '', sfx: '', sfst: {}, mk: [], mkx: '',
  milk: false, title: `${n} · Sănătos`, bridge: null,
  svg: { frontal: `<svg class='tooth-svg' aria-label='${n}'><g class='sfz'><circle data-s='O'/></g></svg>`, occlusal: '<svg></svg>' },
})
const ODO = {
  teeth: { '11': TOOTH(11, 'sus'), '41': TOOTH(41, 'jos') }, history: {},
  arches: { upper: [11], lower: [41], milk_upper: [], milk_lower: [] },
  arc: { upper: [0], lower: [0], milk_upper: [], milk_lower: [] },
  milk_open: false, bridges: [], legend: { frontal: [], occlusal: [] },
  states: { ok: 'Sănătos', carie: 'Carie' }, marks: { tratament: 'În tratament' },
  surfaces: { M: 'mezial', O: 'ocluzal', D: 'distal', V: 'vestibular', L: 'lingual' },
  surface_states: ['carie', 'obturatie'], bridge_roles: { stalp: 'Stâlp', corp: 'Corp de punte' },
  materials: [{ id: 'zirconiu', label: 'Zirconiu' }], patient: { id: 5, name: 'Pin Test', primary_doctor: '' },
  doctors: ['Dr. Activ Doi'],
}

const CARD: PatientCard = {
  id: 5, name: 'Pin Test', initials: 'PT', archived: false, erasure: 'anon',
  profile: {
    name: 'Pin Test', phone: '069000111', birth_date: '1985-03-07', birth: '07.03.1985', gender: 'f',
    gender_label: 'F', idnp: '2000000000001', email: 'pin@example.com', address: 'str. Pin 1',
    insurance: 'CNAM activă', primary_doctor: 'Dr. Activ Doi', file_no: 'D-5', notes: 'nota internă',
    lang: 'ro', age: 41, channel: 'recepție', created: '18.09.2026', year: '2026',
  },
  hero: {
    pills: [
      { tone: 'green', icon: 'check', text: 'Pacient activ' },
      { tone: 'orange', icon: 'sos', text: 'Penicilină' },
      { tone: 'red', icon: 'money', text: 'De achitat: 300 MDL' },
      { tone: 'purple', icon: 'set', text: '1 implant' },
    ],
    last: { date: '17.09.2026', service: 'Consultație' },
    next: { date: '20.09.2026', time: '09:30', service: 'Consultație', doctor: 'Dr. Activ Doi' },
    days_ago: 1,
  },
  kpi: { visits: 3, active: 3, done: 1, canc: 1 },
  alerts: [{ id: 1, kind: 'allergy', label: 'Alergie', icon: 'sos', text: 'Penicilină' }],
  anamneza: {
    filled: true, state: 'risk', n_risk: 3, flags: ['cardio', 'diabet'],
    texts: { boli: '', medicamente: '', alergii: 'latex', anestezie: '' },
    marked: ['Boli cardiovasculare / hipertensiune', 'Diabet zaharat'],
    free: [{ label: 'Alergii (medicamente, materiale)', text: 'latex' }],
    when: '18.09.2026', author: 'Director',
  },
  plan: {
    items: [
      { id: 1, tooth: 11, procedure: 'Coroană 11', doctor: 'Dr. Activ Doi', status: 'in_lucru', label: 'În lucru', price: 1200, due: '', overdue: false, done: '', motiv: '', next: 'finalizat', refusable: true, deletable: false },
      { id: 3, tooth: 48, procedure: 'Extracție 48', doctor: '', status: 'planificat', label: 'Planificat', price: 700, due: '01.01.2020', overdue: true, done: '', motiv: '', next: 'in_lucru', refusable: true, deletable: true },
      { id: 2, tooth: null, procedure: 'Detartraj', doctor: '', status: 'finalizat', label: 'Finalizat', price: 500, due: '', overdue: false, done: '18.09.2026', motiv: '', next: 'in_lucru', refusable: false, deletable: false },
      { id: 5, tooth: 36, procedure: 'Implant 36', doctor: '', status: 'refuzat', label: 'Refuzat', price: 9000, due: '', overdue: false, done: '18.09.2026', motiv: 'refuză implantul', next: 'planificat', refusable: false, deletable: false },
    ],
    counts: { planificat: 1, in_lucru: 1, finalizat: 1, refuzat: 1 },
    n_act: 2, default_tab: 'act', total: 1900, total_done: 500, n_track: 3, pct_done: 33,
  },
  finance: {
    charged: 500, paid: 200, debt: 300, sold: { kind: 'bad', amount: 300 },
    payments: [
      { id: 2, when: '18.09.2026 10:42', method: 'card', icon: 'card', amount: 100, neg: true, note: 'restituire', taken_by: 'Director' },
      { id: 1, when: '18.09.2026 10:42', method: 'numerar', icon: 'cash', amount: 300, neg: false, note: 'avans', taken_by: 'Director' },
    ],
    can_delete: true,
  },
  documents: [
    { id: 3, filename: 'trimitere.docx', when: '18.09.2026', size: '0 KB', mime: '', category: 'trimitere', icon: 'mail', view: 'ext' },
    { id: 1, filename: 'rx.png', when: '18.09.2026', size: '0 KB', mime: 'image/png', category: 'radiografie', icon: 'xray', view: 'img' },
  ],
  visits: {
    history: [
      { id: 4, when: '20.09.2026 09:30', status: 'confirmed', status_label: 'confirmată', service: 'Consultație', doctor: 'Dr. Activ Doi', is_next: true, consult: '', diag: '', url: '/admin/visit/4?back=/admin/patient/5' },
      { id: 3, when: '17.09.2026 12:00', status: 'confirmed', status_label: 'confirmată', service: 'Consultație', doctor: 'Dr. Activ Doi', is_next: false, consult: 'invite', diag: '', url: '/admin/visit/3?back=/admin/patient/5' },
      { id: 1, when: '08.09.2026 10:00', status: 'done', status_label: 'finalizată', service: 'Consultație', doctor: 'Dr. Activ Doi', is_next: false, consult: 'rec', diag: 'Pulpită 26', url: '/admin/visit/1?back=/admin/patient/5' },
    ],
    live: [],
    n_total: 4,
  },
  activity: {
    items: Array.from({ length: 12 }, (_, i) => ({
      id: 100 - i, kind: 'plan_add', icon: 'plus', text: `Eveniment ${i + 1}`, when: '18.09.2026', hhmm: '10:42', who: 'Director',
    })),
    shown: 10, views: false,
  },
  appoint: {
    services: [{ id: 'consult', label: 'Consultație' }, { id: 'hygiene', label: 'Igienizare' }],
    doctors: { consult: ['d2', 'd3'], hygiene: ['d3'] },
    names: { d2: 'Dr. Activ Doi', d3: 'Dr. Activ Trei' },
    primary: 'd2', today: '2026-09-18',
  },
  options: {
    alert_kinds: [{ id: 'allergy', label: 'Alergie' }, { id: 'info', label: 'Info' }],
    anamneza_flags: [{ id: 'cardio', label: 'Boli cardiovasculare / hipertensiune' }, { id: 'diabet', label: 'Diabet zaharat' }],
    anamneza_texts: [{ id: 'alergii', label: 'Alergii (medicamente, materiale)', placeholder: 'ex. penicilină' }],
    doc_categories: [{ id: 'radiografie', label: 'Radiografie' }, { id: 'alt', label: 'Alt document' }],
    max_doc_mb: 25,
    pay_methods: [{ id: 'numerar', icon: 'cash' }, { id: 'card', icon: 'card' }],
    plan_labels: { planificat: 'Planificat', in_lucru: 'În lucru', finalizat: 'Finalizat', refuzat: 'Refuzat' },
    tab_states: { act: ['planificat', 'in_lucru'], finalizat: ['finalizat'], refuzat: ['refuzat'] },
    teeth: [18, 17, 11], milk: [55, 54],
    doctors: ['Dr. Activ Doi', 'Dr. Activ Trei'],
  },
}
CARD.visits.live = CARD.visits.history

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

/** Сервер по адресу: фиша, кусок одонтограммы, лента, часы. */
function serve(card: PatientCard = CARD) {
  get.mockImplementation((path: string) => {
    if (path === '/patients/5' || path === '/patients/5?views=1') return Promise.resolve(ok(card))
    if (path === '/patients/5/odontogram') return Promise.resolve(ok(ODO))
    if (path.startsWith('/patients/5/activity')) {
      return Promise.resolve(ok({ ...card.activity, views: path.includes('views=1'),
        items: [{ id: 999, kind: 'view', icon: 'eye', text: 'Fișa deschisă', when: '18.09.2026', hhmm: '11:00', who: 'Director' }, ...card.activity.items] }))
    }
    if (path.startsWith('/patients/5/slots')) return Promise.resolve(ok({ slots: ['09:00', '09:30'] }))
    return Promise.reject(new Error(`unexpected ${path}`))
  })
}

const rowOf = (text: string) => screen.getByText(text, { selector: '.pp' }).closest('.plan-row') as HTMLElement

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  postForm.mockReset()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/admin/patient/5')
})

describe('mdl', () => {
  it('тысячи пробелом, как в фише', () => {
    expect(mdl(1200)).toBe('1 200')
    expect(mdl(-300)).toBe('300')
    expect(mdl(9000000)).toBe('9 000 000')
  })
})

describe('PatientCardScreen', () => {
  it('успех: шапка, пилюли, KPI, план по вкладке, сальдо, документы, история, летопись, анамнез, профиль', async () => {
    serve()
    render(<PatientCardScreen pid={5} />)
    expect(await screen.findByText('Pin Test', { selector: 'h2' })).toBeTruthy()
    expect(screen.getByText('41 ani')).toBeTruthy()
    expect(screen.getByText('ID #5')).toBeTruthy()
    const pills = Array.from(document.querySelectorAll('.hero-badges .pill')).map((p) => p.textContent?.trim())
    expect(pills).toEqual(['Pacient activ', 'Penicilină', 'De achitat: 300 MDL', '1 implant'])
    // KPI: пять цифр словами старой страницы
    const kpi = Array.from(document.querySelectorAll('.kpi5 .kpi b')).map((b) => b.textContent)
    expect(kpi).toEqual(['3', '3', '1 zile', '20.09', '1'])
    // план: вкладка «Active» по умолчанию прячет закрытые; просрочка; отказ с причиной под вкладкой
    expect(screen.getByText('Coroană 11', { selector: '.pp' })).toBeTruthy()
    expect(screen.queryByText('Detartraj', { selector: '.pp' })).toBeNull()
    expect(screen.getByTitle('Termen depășit').textContent).toContain('01.01.2020')
    expect(screen.getByText('Active (2)').className).toBe('on')
    expect(screen.getByText('Refuzate (1)')).toBeTruthy()
    expect(screen.getByText('1/3 finalizate · 1 refuzate')).toBeTruthy()
    expect(within(rowOf('Coroană 11')).getByText('Finalizează')).toBeTruthy()
    expect(within(rowOf('Extracție 48')).getByText('Începe')).toBeTruthy()
    expect(within(rowOf('Extracție 48')).getByLabelText(/Șterge poziția/)).toBeTruthy()
    expect(within(rowOf('Coroană 11')).queryByLabelText(/Șterge poziția/)).toBeNull()
    expect(screen.getByText('1 900 MDL', { selector: '.ptotal b' })).toBeTruthy()
    // сальдо и платежи
    expect(screen.getByText('De achitat').nextElementSibling?.textContent).toBe('300 MDL')
    expect(screen.getByText('- 100 MDL')).toBeTruthy()
    expect(screen.getAllByLabelText(/Șterge plata/).length).toBe(2)
    // документы: картинка миниатюрой, docx значком
    expect(document.querySelector("img[src='/admin/doc/1?thumb=1']")).toBeTruthy()
    expect(screen.getByTitle('trimitere.docx').querySelector('svg')).toBeTruthy()
    // визиты: следующий отмечен, приглашение и диагноз
    expect(document.querySelector('.tline.next')?.textContent).toContain('20.09.2026 09:30')
    expect((screen.getByText('+ Consultație') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/visit/3?back=/admin/patient/5')
    expect(screen.getByText(/: Pulpită 26/)).toBeTruthy()
    expect(screen.getByText('Următoarea vizită', { selector: '.dp-next h3' })).toBeTruthy()
    // летопись: 10 из 12 и кнопка
    expect(document.querySelectorAll('.acti').length).toBe(10)
    expect(screen.getByText('Toate evenimentele (12)')).toBeTruthy()
    // анамнез: три риска, чипы, дата и автор, опросник свёрнут
    expect(screen.getByText('3 de reținut')).toBeTruthy()
    expect(screen.getByText('Alergii (medicamente, materiale): latex')).toBeTruthy()
    expect(screen.getByText('Completat: 18.09.2026 · Director')).toBeTruthy()
    expect((document.querySelector('details.anform') as HTMLDetailsElement).open).toBe(false)
    // профиль: строки и заметка, форма свёрнута
    expect(screen.getByText('07.03.1985')).toBeTruthy()
    expect(screen.getByText('F', { selector: '.v' })).toBeTruthy()
    expect(screen.getByText(/nota internă/, { selector: '.dp-notes' })).toBeTruthy()
    expect((document.querySelector('.dp-pedit') as HTMLElement).style.display).toBe('none')
    expect(screen.getByText('Arhivează pacientul')).toBeTruthy()
    expect(screen.getByText('datele de identitate')).toBeTruthy()
    // одонтограмма — свой запрос и свой компонент (C21): дуга с кнопками зубов
    await waitFor(() => expect(document.querySelector('#odo .tooth-btn[data-n="11"]')).toBeTruthy())
    expect(get).toHaveBeenCalledWith('/patients/5', expect.anything())
    expect(get).toHaveBeenCalledWith('/patients/5/odontogram', expect.anything())
  })

  it('вкладки плана: Finalizate показывает закрытые, Toate — всё', async () => {
    serve()
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('Finalizate (1)'))
    expect(screen.getByText('Detartraj', { selector: '.pp' })).toBeTruthy()
    expect(screen.queryByText('Coroană 11', { selector: '.pp' })).toBeNull()
    expect(within(rowOf('Detartraj')).getByText('Redeschide')).toBeTruthy()
    fireEvent.click(screen.getByText('Toate (4)'))
    expect(document.querySelectorAll('.plan-row').length).toBe(4)
    expect(screen.getByText('refuză implantul').className).toBe('pmotiv')
    expect(within(rowOf('Implant 36')).getByText('Reia')).toBeTruthy()
  })

  it('план: Finalizează шлёт переход, фиша подменяется, плашка сервера', async () => {
    serve()
    const after: PatientCard = { ...CARD, plan: { ...CARD.plan, default_tab: 'finalizat', n_act: 0 }, kpi: { ...CARD.kpi, active: 0 } }
    post.mockResolvedValueOnce(ok(after, 'ok_refuz', 'Refuzul a fost consemnat'))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(within(rowOf('Coroană 11')).getByText('Finalizează'))
    expect(await screen.findByText('Refuzul a fost consemnat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/plan/1/status', { to: 'finalizat', motiv: '' })
    // сервер сменил вкладку по умолчанию — экран последовал за ним
    expect(screen.getByText('Finalizate (1)').className).toBe('on')
    expect(Array.from(document.querySelectorAll('.kpi5 .kpi b'))[1]?.textContent).toBe('0')
  })

  it('план: отказ без причины — 422 с полем, поле подсвечено, текст сервера; с причиной — уходит', async () => {
    serve()
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_refuz', text: 'Scrieți motivul refuzului', field: 'motiv' }, 'v'))
    post.mockResolvedValueOnce(ok(CARD, 'ok_refuz', 'Refuzul a fost consemnat'))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(within(rowOf('Coroană 11')).getByText('Refuz'))
    const area = screen.getByLabelText(/Motivul refuzului/) as HTMLTextAreaElement
    // пробелы проходят required браузера — отбивает СЕРВЕР (ст. 13(5))
    fireEvent.change(area, { target: { value: '  ' } })
    fireEvent.click(screen.getByText('Înregistrează refuzul'))
    expect(await screen.findByText('Scrieți motivul refuzului')).toBeTruthy()
    expect(area.getAttribute('aria-invalid')).toBe('true')
    fireEvent.change(area, { target: { value: 'nu vrea' } })
    fireEvent.click(screen.getByText('Înregistrează refuzul'))
    await waitFor(() => expect(post).toHaveBeenLastCalledWith('/patients/5/plan/1/status', { to: 'refuzat', motiv: 'nu vrea' }))
  })

  it('предупреждение: добавление шлёт вид и текст; удаление — свой адрес', async () => {
    serve()
    const after = { ...CARD, alerts: [...CARD.alerts, { id: 2, kind: 'info', label: 'Info', icon: 'info', text: 'Vorbește rusă' }] }
    post.mockResolvedValueOnce(ok(after, 'ok_card', 'Fișa pacientului a fost actualizată'))
    post.mockResolvedValueOnce(ok(CARD))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.change(screen.getByLabelText('Atenționări medicale'), { target: { value: 'info' } })
    fireEvent.change(screen.getByLabelText('ex. Alergie: Penicilină'), { target: { value: 'Vorbește rusă' } })
    fireEvent.click(screen.getByText('+ Adaugă'))
    expect(await screen.findByText(/Vorbește rusă/, { selector: '.alert' })).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/alerts', { kind: 'info', text: 'Vorbește rusă' })
    expect((screen.getByLabelText('ex. Alergie: Penicilină') as HTMLInputElement).value).toBe('')
    fireEvent.click(screen.getByLabelText('Șterge: Vorbește rusă'))
    await waitFor(() => expect(post).toHaveBeenLastCalledWith('/patients/5/alerts/2/delete', {}))
  })

  it('профиль: правка шлёт все поля; 422 bad_idnp подсвечивает IDNP и оставляет форму', async () => {
    serve()
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_idnp', text: 'IDNP trebuie să aibă exact 13 cifre', field: 'idnp' }, 'v'))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('Editează profilul'))
    expect((document.querySelector('.dp-pedit') as HTMLElement).style.display).toBe('flex')
    fireEvent.change(screen.getByLabelText('IDNP (opțional)'), { target: { value: '12' } })
    fireEvent.click(screen.getByText('Salvează profilul'))
    expect(await screen.findByText('IDNP trebuie să aibă exact 13 cifre')).toBeTruthy()
    expect(screen.getByLabelText('IDNP (opțional)').getAttribute('aria-invalid')).toBe('true')
    expect(post).toHaveBeenCalledWith('/patients/5/profile', {
      name: 'Pin Test', phone: '069000111', birth_date: '1985-03-07', gender: 'f', idnp: '12',
      email: 'pin@example.com', address: 'str. Pin 1', insurance: 'CNAM activă',
      primary_doctor: 'Dr. Activ Doi', file_no: 'D-5', notes: 'nota internă', lang: 'ro',
    })
    expect((document.querySelector('.dp-pedit') as HTMLElement).style.display).toBe('flex')
  })

  it('платёж: форма шлёт сумму, метод и заметку; без права — кнопок удаления нет', async () => {
    serve({ ...CARD, finance: { ...CARD.finance, can_delete: false } })
    post.mockResolvedValueOnce(ok(CARD, 'ok_pay', 'Plata a fost înregistrată'))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(screen.queryAllByLabelText(/Șterge plata/).length).toBe(0)
    fireEvent.change(screen.getByLabelText('Suma MDL (cu minus = restituire)'), { target: { value: '250' } })
    fireEvent.change(screen.getByLabelText('Metoda'), { target: { value: 'card' } })
    fireEvent.change(screen.getByLabelText('Notă (opțional, ex. avans coroană)'), { target: { value: 'avans' } })
    fireEvent.click(screen.getByText('＋ Înregistrează plata'))
    expect(await screen.findByText('Plata a fost înregistrată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/payments', { amount: '250', method: 'card', note: 'avans' })
  })

  it('стирание: контакт без лечения — уход по адресу сервера', async () => {
    serve({ ...CARD, erasure: 'delete' })
    post.mockResolvedValueOnce(ok({ url: '/admin/search?msg=ok_del' }, 'ok_del', 'Fișa a fost ștearsă'))
    const navigate = vi.fn()
    render(<PatientCardScreen pid={5} navigate={navigate} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(screen.getByText('ștearsă definitiv')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('scrieți STERG'), { target: { value: 'sterg' } })
    fireEvent.click(screen.getByText('Șterge definitiv'))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/search?msg=ok_del'))
    expect(post).toHaveBeenCalledWith('/patients/5/erase', { confirm: 'sterg' })
  })

  it('запись: диалог тянет часы у движка и шлёт запись', async () => {
    serve()
    post.mockResolvedValueOnce(ok(CARD, 'ok', 'Programare adăugată'))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('Programează'))
    expect(await screen.findByText('2 intervale libere în această zi')).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/patients/5/slots?date=2026-09-18&doctor=d2&service=consult', expect.anything())
    fireEvent.change(screen.getByLabelText('Ora — doar intervalele libere'), { target: { value: '09:30' } })
    fireEvent.click(screen.getByText('Adaugă programarea'))
    expect(await screen.findByText('Programare adăugată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/appoint', { date: '2026-09-18', time: '09:30', doctor: 'd2', service: 'consult' })
  })

  it('летопись: «Toate» раскрывает; «accesările» тянет ленту отдельно и меняет адрес', async () => {
    serve()
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('Toate evenimentele (12)'))
    expect(document.querySelectorAll('.acti').length).toBe(12)
    fireEvent.click(screen.getByText('accesările'))
    expect(await screen.findByText('Fișa deschisă')).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/patients/5/activity?views=1')
    expect(window.location.search).toBe('?views=1')
    expect(screen.getByText('ascunde accesările')).toBeTruthy()
  })

  it('документ для чужой программы: движок не открыл — скачивание', async () => {
    serve()
    post.mockResolvedValueOnce(ok({ opened: false, reason: 'not_local' }))
    const navigate = vi.fn()
    render(<PatientCardScreen pid={5} navigate={navigate} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByTitle('trimitere.docx'))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/doc/3'))
    expect(post).toHaveBeenCalledWith('/documents/3/open', {})
  })

  it('архив: серая пилюля и кнопка возврата', async () => {
    serve({ ...CARD, archived: true, hero: { ...CARD.hero, pills: [{ tone: 'grey', icon: 'box', text: 'Arhivat' }] } })
    post.mockResolvedValueOnce(ok(CARD, 'ok_unarh', 'Pacient scos din arhivă'))
    render(<PatientCardScreen pid={5} />)
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(screen.getByText('Arhivat', { selector: '.pill' })).toBeTruthy()
    fireEvent.click(screen.getByText('Scoate din arhivă'))
    expect(await screen.findByText('Pacient scos din arhivă')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/archive', { on: false })
  })

  it('фиши нет — 404 своим текстом; 401 — уход на вход', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 's'))
    render(<PatientCardScreen pid={5} />)
    expect(await screen.findByText('Fișa nu există sau a fost ștearsă.')).toBeTruthy()
    cleanup()
    get.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    render(<PatientCardScreen pid={5} navigate={navigate} />)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})
