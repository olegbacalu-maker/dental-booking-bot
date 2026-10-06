import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../../services/api'
import { openScreen } from '../../../test/openScreen'
import { ApiError } from '../../../types/api'
import type { PerioModel } from '../../clinical/perio'
import type { VisitPage } from '../../visits/visits'
import type { PatientCard } from './card'
import { mdl } from './card'
import { loadPatientCard, PatientCardScreen } from './PatientCardScreen'

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

/* пародонтограмма — минимальный осмотр: два зуба, шесть точек */
const PEXAM = { id: 9, at: '18.09.2026', doctor: 'Dr. Activ Doi', note: '', teeth: 1 }
const PERIO: PerioModel = {
  patient: { id: 5, name: 'Pin Test' }, rev: 'r1', exams: [PEXAM, { id: 4, at: '01.03.2026', doctor: '', note: '', teeth: 0 }], exam: PEXAM,
  rows: { '16': { tooth: 16, pd: [3, 2, 3, 4, 2, 5], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [3, 2, 3, 4, 2, 5] } },
  teeth: {
    '16': { state: 'ok', absent: false, title: '16 · Sănătos', svg: { frontal: '', occlusal: '' } },
    '46': { state: 'ok', absent: false, title: '46 · Sănătos', svg: { frontal: '', occlusal: '' } },
  },
  arches: { upper: [16], lower: [46] },
  sites: [
    { key: 'MV', label: 'mezio-vestibular' }, { key: 'V', label: 'vestibular' }, { key: 'DV', label: 'disto-vestibular' },
    { key: 'ML', label: 'mezio-lingual' }, { key: 'L', label: 'lingual / palatinal' }, { key: 'DL', label: 'disto-lingual' },
  ],
  summary: { teeth: 1, sites: 6, bop: 0, pd_mean: 3.2, cal_mean: 3.2, deep: 2, severe: 0, mob: [], furc: [] },
  limits: { mm_max: 12, mob_max: 3, furc_max: 3, deep: 4, severe: 6 },
  grades: { mob: { '1': 'gr. I' }, furc: { '1': 'gr. I' } }, doctors: ['Dr. Activ Doi'],
}

/* дневник визита — страница визита 3 этого пациента, `back` — эхо адреса вкладки */
const VPAGE: VisitPage = {
  appt: { id: 3, when: '20.09.2026 09:30', patient_id: 5, patient: 'Pin Test', service: 'Consultație',
    doctor: 'Dr. Activ Doi', status: 'confirmed', status_label: 'confirmată', comment: '' },
  record: null, editable: true, note: '',
  fields: [
    { id: 'acuze', label: 'Acuze / motivul prezentării', rows: 2, placeholder: '' },
    { id: 'examen', label: 'Examen obiectiv', rows: 3, placeholder: '' },
    { id: 'diagnostic', label: 'Diagnostic', rows: 2, placeholder: '' },
    { id: 'tratament', label: 'Tratament efectuat', rows: 3, placeholder: '' },
    { id: 'recomandari', label: 'Recomandări', rows: 2, placeholder: '' },
  ],
  templates: [], plan: { linked: [], open: [] },
  back: '/admin/patient/5?tab=vizite',
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
    free: [{ label: 'Alergii (medicamente, materiale)', text: 'latex', short: 'Alergii' }],
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
    { id: 3, filename: 'trimitere.docx', when: '18.09.2026', size: '0 KB', mime: '', category: 'trimitere', category_label: 'Trimitere', icon: 'mail', view: 'ext' },
    { id: 1, filename: 'rx.png', when: '18.09.2026', size: '0 KB', mime: 'image/png', category: 'radiografie', category_label: 'Radiografie', icon: 'xray', view: 'img' },
  ],
  forms: [
    { key: 'acord195', title: 'Informare și acord (Legea 195)', sheet: 'acord', category: 'acord195', printed: '', signed: null },
    { key: 'acord_plan', title: 'Acord informat la planul de tratament', sheet: 'plan-acord', category: 'acord_plan', printed: '18.09.2026', signed: null, n_active: 2, total: 1900, stale: false },
    { key: 'chestionar', title: 'Chestionar anamneză', sheet: 'anamneza/print', category: 'chestionar', printed: '', signed: null, filled: '18.09.2026' },
    { key: 'fisa043', title: 'Fișa 043/e', sheet: 'fisa043', category: 'fisa043', printed: '', signed: null },
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
    doc_categories: [{ id: 'radiografie', label: 'Radiografie' }, { id: 'acord_plan', label: 'Acord informat la plan — semnat' }, { id: 'alt', label: 'Alt document' }],
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

/** Лента в режиме: с ?views=1 сервер добавляет просмотры (журнал доступа) и отражает режим. */
const feed = (card: PatientCard, views: boolean) => (views
  ? { ...card.activity, views, items: [{ id: 999, kind: 'view', icon: 'eye', text: 'Fișa deschisă', when: '18.09.2026', hhmm: '11:00', who: 'Director' }, ...card.activity.items] }
  : { ...card.activity, views })

/** Сервер по адресу: фиша (в режиме ленты из адреса), кусок одонтограммы, лента, часы. */
function serve(card: PatientCard = CARD) {
  get.mockImplementation((path: string) => {
    if (path === '/patients/5') return Promise.resolve(ok(card))
    if (path === '/patients/5?views=1') return Promise.resolve(ok({ ...card, activity: feed(card, true) }))
    if (path === '/patients/5/odontogram') return Promise.resolve(ok(ODO))
    if (path === '/scan/status') return Promise.resolve(ok({ ok: true, name: 'Scaner de test' }))
    if (path.startsWith('/patients/5/activity')) return Promise.resolve(ok(feed(card, path.includes('views=1'))))
    if (path.startsWith('/patients/5/slots')) return Promise.resolve(ok({ slots: ['09:00', '09:30'] }))
    if (path.startsWith('/visits/3')) return Promise.resolve(ok(VPAGE))
    if (path.startsWith('/patients/5/perio')) {
      /* как сервер: осмотр из адреса; неизвестный или без адреса — свежий */
      const id = new URLSearchParams(path.split('?')[1] ?? '').get('exam')
      const ex = PERIO.exams.find((x) => String(x.id) === id) ?? PERIO.exam
      return Promise.resolve(ok({ ...PERIO, exam: ex, rows: ex?.id === PERIO.exam?.id ? PERIO.rows : {} }))
    }
    return Promise.reject(new Error(`unexpected ${path}`))
  })
}

const rowOf = (text: string) => screen.getByText(text, { selector: '.pp' }).closest('.plan-row') as HTMLElement

/** Фиша по адресу — тем же маршрутом, что в App.tsx: загрузчик роутера и его правило перезапуска. */
const open = (url = '/admin/patient/5', navigate?: (url: string) => void) => openScreen(
  '/admin/patient/:pid', url, <PatientCardScreen pid={5} {...(navigate ? { navigate } : {})} />,
  loadPatientCard, navigate)

/** Сколько раз фиша ОТКРЫВАЛАСЬ (полная загрузка — на сервере это запись «Fișa deschisă»). */
const opens = () => get.mock.calls.filter(([p]) => p === '/patients/5' || p === '/patients/5?views=1').length

/** Фиша дорисована: оба запроса загрузчика (фиша и карта — `Promise.all`) уже ушли,
 *  дальше запросы только наши. Дуга — на вкладке «Odontogramă», см. `odoReady`. */
const settled = () => screen.findByText('Pin Test', { selector: 'h2' })

/** Дуга компактной одонтограммы нарисована (вкладка «Odontogramă» открыта). */
const odoReady = () => waitFor(() => expect(document.querySelector('#odo .tooth-btn[data-n="11"]')).toBeTruthy())

/** Полоса вкладок фиши (B6) — своим именем: у плана внутри свои вкладки. */
const strip = () => within(screen.getByRole('tablist', { name: 'Secțiunile fișei' }))

/** Щелчок по вкладке фиши и ожидание, пока роутер её откроет (адрес — `?tab=`). */
const tabTo = async (name: string) => {
  fireEvent.click(strip().getByRole('tab', { name }))
  await strip().findByRole('tab', { name, selected: true })
}
const tabOn = () => strip().getByRole('tab', { selected: true }).textContent

/** F5: свежий роутер на адресе, который оставил экран; подмена сети та же, счёт вызовов — с нуля. */
const reopen = (router: ReturnType<typeof open>['router']) => {
  const url = router.state.location.pathname + router.state.location.search
  cleanup()
  get.mockClear()
  return open(url)
}

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  postForm.mockReset()
  vi.restoreAllMocks()
})

describe('mdl', () => {
  it('тысячи пробелом, как в фише', () => {
    expect(mdl(1200)).toBe('1 200')
    expect(mdl(-300)).toBe('300')
    expect(mdl(9000000)).toBe('9 000 000')
  })
})

describe('PatientCardScreen', () => {
  /* ⚠️ Самая тяжёлая проверка набора, и предел у неё СВОЙ (06.10). Вкладки
     обходятся в ОДНОЙ проверке намеренно: её утверждение — «за весь обход фиша
     открыта один раз» (журнал доступа); первой в файле она ещё и платит за
     прогрев всех карточек фиши. Поодиночке — 0,5–0,6 с, в полном прогоне на
     машине разработчика — 1,4–5,4 с, и замер по шагам показал: медленнее
     становятся ВСЕ шаги поровну, то есть не хватает процессора параллельным
     jsdom, а не висит ожидание. Стандартные 5 с vitest её обрывали. Зависший
     шаг по-прежнему ловит предел `waitFor` (3 с, src/test/setup.ts). */
  it('успех: шапка и Rezumat сразу; остальное — по вкладкам, без нового открытия фиши', { timeout: 15_000 }, async () => {
    serve()
    const { router } = open()
    expect(await screen.findByText('Pin Test', { selector: 'h2' })).toBeTruthy()
    expect(screen.getByText('41 ani')).toBeTruthy()
    expect(screen.getByText('ID #5')).toBeTruthy()
    const pills = Array.from(document.querySelectorAll('.hero-badges .pill')).map((p) => p.textContent?.trim())
    expect(pills).toEqual(['Pacient activ', 'Penicilină', 'De achitat: 300 MDL', '1 implant'])
    // KPI: пять цифр словами старой страницы
    const kpi = Array.from(document.querySelectorAll('.kpi5 .kpi b')).map((b) => b.textContent)
    expect(kpi).toEqual(['3', '3', '1 zile', '20.09', '1'])
    // B6: шесть вкладок, открыта «Rezumat»; с других вкладок ничего не смонтировано
    expect(strip().getAllByRole('tab').map((x) => x.textContent))
      .toEqual(['Rezumat', 'Odontogramă', 'Parodontogramă', 'Plan și plăți', 'Vizite', 'Documente', 'Date pacient'])
    expect(tabOn()).toBe('Rezumat')
    expect(router.state.location.search).toBe('')
    expect(document.querySelector('#odo')).toBeNull()
    expect(screen.queryByText('Coroană 11', { selector: '.pp' })).toBeNull()
    expect(document.querySelector('.dp-pedit')).toBeNull()
    // Rezumat: ближайший визит, история, предупреждения, летопись, быстрые действия
    expect(document.querySelector('.tline.next')?.textContent).toContain('20.09.2026 09:30')
    /* B6 шаг 4: дневник открывается во вкладке Vizite, визит — адресом */
    expect((screen.getByText('+ Consultație') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/patient/5?tab=vizite&visit=3')
    expect(screen.getByText(/: Pulpită 26/)).toBeTruthy()
    expect(screen.getByText('Următoarea vizită', { selector: '.dp-next h3' })).toBeTruthy()
    expect(document.querySelectorAll('.acti').length).toBe(10)
    expect(screen.getByText('Toate evenimentele (12)')).toBeTruthy()
    expect(screen.getByText(/Penicilină/, { selector: '.alert' })).toBeTruthy()
    expect(screen.getByText('Acțiuni rapide')).toBeTruthy()
    // план и платежи — вкладка «Plan și plăți»: вкладка «Active» прячет закрытые; просрочка; отказ с причиной
    await tabTo('Plan și plăți')
    expect(router.state.location.search).toBe('?tab=plan')
    expect(screen.getByText('Coroană 11', { selector: '.pp' })).toBeTruthy()
    expect(screen.queryByText('Detartraj', { selector: '.pp' })).toBeNull()
    expect(screen.getByTitle('Termen depășit').textContent).toContain('01.01.2020')
    expect(screen.getByText('Active (2)').className).toBe('on')
    expect(screen.getByText('Refuzate (1)')).toBeTruthy()
    expect(screen.getByText('1/3 finalizate · 1 refuzate')).toBeTruthy()
    expect(within(rowOf('Coroană 11')).getByText('Finalizează')).toBeTruthy()
    expect(within(rowOf('Extracție 48')).getByText('Începe')).toBeTruthy()
    /* отказ и удаление — в меню «⋯» строки (01.10); что в нём — отдельная проверка ниже */
    expect(within(rowOf('Extracție 48')).getByRole('button', { name: /Mai multe acțiuni/ })).toBeTruthy()
    expect(within(rowOf('Extracție 48')).queryByLabelText(/Șterge poziția/)).toBeNull()
    expect(screen.getByText('1 900 MDL', { selector: '.ptotal b' })).toBeTruthy()
    // сальдо и платежи
    expect(screen.getByText('De achitat').nextElementSibling?.textContent).toBe('300 MDL')
    expect(screen.getByText('- 100 MDL')).toBeTruthy()
    expect(screen.getAllByLabelText(/Șterge plata/).length).toBe(2)
    // документы: картинка миниатюрой, docx значком
    await tabTo('Documente')
    expect(document.querySelector("img[src='/admin/doc/1?thumb=1']")).toBeTruthy()
    expect(screen.getByTitle('trimitere.docx').querySelector('svg')).toBeTruthy()
    // данные пациента: профиль (строки и заметка, форма свёрнута) и анамнез (три риска, чипы, дата и автор, опросник свёрнут)
    await tabTo('Date pacient')
    expect(screen.getByText('07.03.1985')).toBeTruthy()
    expect(screen.getByText('F', { selector: '.v' })).toBeTruthy()
    expect(screen.getByText(/nota internă/, { selector: '.dp-notes' })).toBeTruthy()
    expect((document.querySelector('.dp-pedit') as HTMLElement).style.display).toBe('none')
    expect(screen.getByText('Arhivează pacientul')).toBeTruthy()
    expect(screen.getByText('datele de identitate')).toBeTruthy()
    expect(screen.getByText('3 de reținut')).toBeTruthy()
    expect(screen.getByText('Alergii (medicamente, materiale): latex')).toBeTruthy()
    expect(screen.getByText('Completat: 18.09.2026 · Director')).toBeTruthy()
    expect((document.querySelector('details.anform') as HTMLDetailsElement).open).toBe(false)
    // одонтограмма — рабочий стол детальной (инспектор рядом с дугой), модель — из загрузчика, без второго запроса
    await tabTo('Odontogramă')
    await odoReady()
    expect(document.querySelector('.odop .insp')).toBeTruthy()
    expect(screen.getByText('Pe tot ecranul').closest('a')?.getAttribute('href')).toBe('/admin/patient/5/odontograma')
    expect(get).toHaveBeenCalledWith('/patients/5', expect.anything())
    expect(get).toHaveBeenCalledWith('/patients/5/odontogram', expect.anything())
    expect(get.mock.calls.filter(([p]) => p === '/patients/5/odontogram').length).toBe(1)
    // пять вкладок пройдены — фиша ОТКРЫТА один раз (в журнале доступа одна «Fișa deschisă»)
    expect(opens()).toBe(1)
  })

  it('вкладки плана: Finalizate показывает закрытые, Toate — всё', async () => {
    serve()
    open('/admin/patient/5?tab=plan')
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
    open('/admin/patient/5?tab=plan')
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
    open('/admin/patient/5?tab=plan')
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(within(rowOf('Coroană 11')).getByRole('button', { name: /Mai multe acțiuni/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /Refuz/ }))
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
    open()
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

  it('удаление того, чего уже нет (сняли с другого места): 404 — плашка сервера, фиша остаётся', async () => {
    /* ⚠️ Сервер отвечает 404 с кодом и текстом и БЕЗ фиши: тихий успех отдавал
       фишу целиком мимо журнала доступа. 404 действия — не «фиши нет». */
    serve()
    post.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: 'alert_gone', text: 'Atenționarea nu mai există — reîmprospătați pagina' }, 's'))
    open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByLabelText('Șterge: Penicilină'))
    expect(await screen.findByText('Atenționarea nu mai există — reîmprospătați pagina')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/alerts/1/delete', {})
    expect(screen.getByText('Pin Test', { selector: 'h2' })).toBeTruthy()
    expect(screen.getByText(/Penicilină/, { selector: '.alert' })).toBeTruthy()
    expect(screen.queryByText('Fișa nu există sau a fost ștearsă.')).toBeNull()
  })

  it('профиль: правка шлёт все поля; 422 bad_idnp подсвечивает IDNP и оставляет форму', async () => {
    serve()
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_idnp', text: 'IDNP trebuie să aibă exact 13 cifre', field: 'idnp' }, 'v'))
    open('/admin/patient/5?tab=date')
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
    open('/admin/patient/5?tab=plan')
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(screen.queryAllByLabelText(/Șterge plata/).length).toBe(0)
    fireEvent.change(screen.getByLabelText('Suma MDL (cu minus = restituire)'), { target: { value: '250' } })
    fireEvent.change(screen.getByLabelText('Metoda'), { target: { value: 'card' } })
    fireEvent.change(screen.getByLabelText('Notă (opțional, ex. avans coroană)'), { target: { value: 'avans' } })
    fireEvent.click(screen.getByText('＋ Înregistrează plata'))
    expect(await screen.findByText('Plata a fost înregistrată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/payments', { amount: '250', method: 'card', note: 'avans' })
  })

  it('одонтограмма приезжает С ФИШЕЙ: дуга в том же кадре, что и шапка, и запрос один', async () => {
    serve()
    open('/admin/patient/5?tab=odonto')
    await screen.findByText('Pin Test', { selector: 'h2' })
    /* без waitFor: дуга обязана быть УЖЕ в кадре шапки — иначе всё под ней прыгнет */
    expect(document.querySelector('#odo .tooth-btn[data-n="11"]')).toBeTruthy()
    expect(get.mock.calls.filter(([p]) => p === '/patients/5/odontogram').length).toBe(1)
    expect(opens()).toBe(1)
  })

  it('карта не ответила загрузчику — фиша открывается, карточка грузит сама и говорит об отказе', async () => {
    serve()
    const base = get.getMockImplementation()!
    get.mockImplementation((path: string) => (path === '/patients/5/odontogram'
      ? Promise.reject(new ApiError({ kind: 'network', detail: 'down' }, 'n'))
      : base(path)))
    open('/admin/patient/5?tab=odonto')
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(await screen.findByText('Formula dentară nu s-a încărcat.')).toBeTruthy()
    expect(get.mock.calls.filter(([p]) => p === '/patients/5/odontogram').length).toBe(2)
  })

  it('стирание: контакт без лечения — уход по адресу сервера', async () => {
    serve({ ...CARD, erasure: 'delete' })
    post.mockResolvedValueOnce(ok({ url: '/admin/search?msg=ok_del' }, 'ok_del', 'Fișa a fost ștearsă'))
    const navigate = vi.fn()
    const { router } = open('/admin/patient/5?tab=date', navigate)
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(screen.getByText('ștearsă definitiv')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('scrieți STERG'), { target: { value: 'sterg' } })
    fireEvent.click(screen.getByText('Șterge definitiv'))
    /* B4: в список — ПЕРЕХОДОМ (плашку «ștearsă» несёт адрес); `navigate` экрана — входу */
    await waitFor(() => expect(router.state.location.pathname + router.state.location.search)
      .toBe('/admin/search?msg=ok_del'))
    expect(navigate).not.toHaveBeenCalled()
    expect(post).toHaveBeenCalledWith('/patients/5/erase', { confirm: 'sterg' })
  })

  it('запись: диалог тянет часы у движка и шлёт запись', async () => {
    serve()
    post.mockResolvedValueOnce(ok(CARD, 'ok', 'Programare adăugată'))
    open()
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
    const { router } = open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('Toate evenimentele (12)'))
    expect(document.querySelectorAll('.acti').length).toBe(12)
    fireEvent.click(screen.getByText('accesările'))
    expect(await screen.findByText('Fișa deschisă')).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/patients/5/activity?views=1')
    /* ⭐ Адрес ведёт РОУТЕР (не history мимо него): его и читают загрузчик и действия. */
    await waitFor(() => expect(router.state.location.search).toBe('?views=1'))
    expect(screen.getByText('ascunde accesările')).toBeTruthy()
    /* переключатель не открывает фишу заново: одна полная загрузка — одна запись в журнале */
    expect(opens()).toBe(1)
  })

  it('пока лента едет — прежняя фиша без сброса в ожидание; адрес меняется ПОСЛЕ данных', async () => {
    serve()
    const base = get.getMockImplementation()
    let arrive = () => {}
    get.mockImplementation((path: string) => (path.startsWith('/patients/5/activity')
      ? new Promise<void>((res) => { arrive = res }).then(() => base?.(path))
      : base?.(path)))
    const { router } = open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('accesările'))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/patients/5/activity?views=1'))
    expect(screen.getByText('Pin Test', { selector: 'h2' })).toBeTruthy()
    expect(document.querySelector('.dp-hero-wait')).toBeNull()
    expect(screen.getByText('accesările')).toBeTruthy()
    expect(router.state.location.search).toBe('')
    await act(async () => { arrive() })
    await screen.findByText('ascunde accesările')
    await waitFor(() => expect(router.state.location.search).toBe('?views=1'))
  })

  it('переключатель ленты не перезапускает загрузчик, а повтор — перезапускает, и уже по новому адресу', async () => {
    serve()
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'offline' }, 'n'))
    const { router } = open()
    fireEvent.click(await screen.findByText('Reîncearcă'))
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(opens()).toBe(2)
    fireEvent.click(screen.getByText('accesările'))
    await screen.findByText('ascunde accesările')
    await waitFor(() => expect(router.state.location.search).toBe('?views=1'))
    expect(opens()).toBe(2)
    /* перезапуск на том же адресе (так работает «Reîncearcă») — загрузчик видит УЖЕ новый адрес */
    await act(() => router.revalidate())
    /* последним уходит запрос карты (загрузчик просит обе разом) — важен сам факт запроса фиши по новому адресу */
    expect(get).toHaveBeenCalledWith('/patients/5?views=1', expect.anything())
    expect(opens()).toBe(3)
    expect(screen.getByText('Fișa deschisă')).toBeTruthy()
  })

  it('F5 после «accesările»: тот же адрес — та же фиша в том же режиме ленты', async () => {
    serve()
    const { router } = open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    await settled()
    fireEvent.click(screen.getByText('accesările'))
    await screen.findByText('ascunde accesările')
    await waitFor(() => expect(router.state.location.search).toBe('?views=1'))
    const asked = get.mock.calls.at(-1)?.[0] as string
    expect(asked).toBe('/patients/5/activity?views=1')
    reopen(router)
    await screen.findByText('ascunde accesările')
    /* тот же набор: полная загрузка в том же режиме, что принёс переключатель */
    expect(get.mock.calls[0]?.[0]).toBe(asked.replace('/activity', ''))
    expect(screen.getByText('Fișa deschisă')).toBeTruthy()
  })

  it('F5 после «ascunde accesările»: адрес без query (и без прежнего ?msg=) — фиша без просмотров', async () => {
    serve()
    const { router } = open('/admin/patient/5?views=1&msg=ok_card')
    await screen.findByText('ascunde accesările')
    expect(screen.getByText('Fișa deschisă')).toBeTruthy()
    await settled()
    fireEvent.click(screen.getByText('ascunde accesările'))
    await screen.findByText('accesările')
    await waitFor(() => expect(router.state.location.search).toBe(''))
    expect(router.state.location.pathname).toBe('/admin/patient/5')
    const asked = get.mock.calls.at(-1)?.[0] as string
    expect(asked).toBe('/patients/5/activity')
    expect(opens()).toBe(1)
    reopen(router)
    await screen.findByText('accesările')
    expect(get.mock.calls[0]?.[0]).toBe(asked.replace('/activity', ''))
    expect(screen.queryByText('Fișa deschisă')).toBeNull()
  })

  it('режим ленты — из адреса: повтор ключа решает последний, как у сервера; действия несут режим адреса', async () => {
    serve()
    post.mockResolvedValue(ok(CARD))
    open('/admin/patient/5?views=1&views=0')
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(get).toHaveBeenCalledWith('/patients/5', expect.anything())
    cleanup()
    get.mockClear()
    open('/admin/patient/5?views=0&views=1')
    await screen.findByText('ascunde accesările')
    expect(get).toHaveBeenCalledWith('/patients/5?views=1', expect.anything())
    await tabTo('Date pacient')
    fireEvent.click(screen.getByText('Arhivează pacientul'))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/patients/5/archive?views=1', { on: true }))
    cleanup()
    post.mockClear()
    /* после переключения действие уходит в НОВОМ режиме: второй копии режима у экрана нет */
    open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('accesările'))
    await screen.findByText('ascunde accesările')
    await tabTo('Date pacient')
    fireEvent.click(screen.getByText('Arhivează pacientul'))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/patients/5/archive?views=1', { on: true }))
  })

  it('зуб из фиши: свежая фиша едет в ответе записи, а не новым открытием (журнал доступа)', async () => {
    /* ⚠️ Раньше фиша перечитывала себя GET-ом после записи зуба — на сервере
       это ОТКРЫТИЕ, и каждое сохранение зуба писало ложное «Fișa deschisă». */
    const after: PatientCard = {
      ...CARD, hero: { ...CARD.hero, pills: [...CARD.hero.pills.slice(0, 3), { tone: 'purple', icon: 'set', text: '2 implante' }] },
    }
    const saveTooth11 = async () => {
      await odoReady()
      fireEvent.click(document.querySelector('#odo .tooth-btn[data-n="11"]') as HTMLElement)
      /* B6 шаг 2: во вкладке тот же рабочий стол, что на детальной — инспектор, не диалог */
      const insp = document.querySelector('.insp') as HTMLElement
      expect(within(insp).getByText('11', { selector: '.insp-n b' })).toBeTruthy()
      fireEvent.change(within(insp).getByLabelText('Starea dintelui'), { target: { value: 'carie' } })
      fireEvent.click(within(insp).getByText('Salvează'))
      expect(await screen.findByText('Fișa pacientului a fost actualizată')).toBeTruthy()
    }
    const pills = () => Array.from(document.querySelectorAll('.hero-badges .pill')).map((p) => p.textContent?.trim())
    serve()
    post.mockResolvedValueOnce(ok({ ...ODO, card: after }, 'ok_card', 'Fișa pacientului a fost actualizată'))
    open('/admin/patient/5?tab=odonto')
    await screen.findByText('Pin Test', { selector: 'h2' })
    await saveTooth11()
    expect(opens()).toBe(1)
    expect(post).toHaveBeenCalledWith('/patients/5/teeth/11?card=1', expect.objectContaining({ state: 'carie', state0: 'ok' }))
    await waitFor(() => expect(pills()).toContain('2 implante'))
    expect(opens()).toBe(1)
    /* режим ленты адреса едет и в запись: фиша в ответе — с просмотрами */
    cleanup()
    get.mockClear()
    post.mockReset()
    post.mockResolvedValueOnce(ok({ ...ODO, card: { ...after, activity: feed(after, true) } }, 'ok_card', 'Fișa pacientului a fost actualizată'))
    open('/admin/patient/5?tab=odonto&views=1')
    await saveTooth11()
    expect(post).toHaveBeenCalledWith('/patients/5/teeth/11?card=1&views=1', expect.anything())
    await waitFor(() => expect(pills()).toContain('2 implante'))
    /* лента из ответа записи — с просмотрами: видно на Rezumat, без нового открытия */
    await tabTo('Rezumat')
    expect(screen.getByText('ascunde accesările')).toBeTruthy()
    expect(opens()).toBe(1)
  })

  it('документ для чужой программы: движок не открыл — скачивание', async () => {
    serve()
    post.mockResolvedValueOnce(ok({ opened: false, reason: 'not_local' }))
    const navigate = vi.fn()
    open('/admin/patient/5?tab=docs', navigate)
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByTitle('trimitere.docx'))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/doc/3'))
    expect(post).toHaveBeenCalledWith('/documents/3/open', {})
  })

  it('архив: серая пилюля и кнопка возврата', async () => {
    serve({ ...CARD, archived: true, hero: { ...CARD.hero, pills: [{ tone: 'grey', icon: 'box', text: 'Arhivat' }] } })
    post.mockResolvedValueOnce(ok(CARD, 'ok_unarh', 'Pacient scos din arhivă'))
    open('/admin/patient/5?tab=date')
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(screen.getByText('Arhivat', { selector: '.pill' })).toBeTruthy()
    fireEvent.click(screen.getByText('Scoate din arhivă'))
    expect(await screen.findByText('Pacient scos din arhivă')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/archive', { on: false })
  })

  it('фиши нет — 404 своим текстом; 401 — уход на вход', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 's'))
    open()
    expect(await screen.findByText('Fișa nu există sau a fost ștearsă.')).toBeTruthy()
    cleanup()
    get.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open('/admin/patient/5', navigate)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })

  it('B6 вкладки: адрес ведёт вкладку, неизвестная — Rezumat; щелчок меняет адрес без нового открытия; F5 держит', async () => {
    serve()
    const { router } = open('/admin/patient/5?tab=xyz')
    await screen.findByText('Pin Test', { selector: 'h2' })
    expect(tabOn()).toBe('Rezumat')
    expect(document.querySelector('#odo')).toBeNull()
    await tabTo('Odontogramă')
    expect(router.state.location.search).toBe('?tab=odonto')
    await odoReady()
    expect(opens()).toBe(1)
    /* F5 на этом адресе — та же вкладка; загрузчик снова просит обе разом */
    const r2 = reopen(router)
    await screen.findByText('Pin Test', { selector: 'h2' })
    await strip().findByRole('tab', { name: 'Odontogramă', selected: true })
    await odoReady()
    expect(opens()).toBe(1)
    expect(r2.router.state.location.search).toBe('?tab=odonto')
    /* назад к Rezumat — умолчание в адрес не пишется, одонтограмма размонтирована */
    await tabTo('Rezumat')
    expect(r2.router.state.location.search).toBe('')
    expect(document.querySelector('#odo')).toBeNull()
    expect(opens()).toBe(1)
  })

  it('B6 вкладка и режим ленты — один адрес; адрес действия вкладку не несёт', async () => {
    serve()
    post.mockResolvedValue(ok({ ...CARD, activity: feed(CARD, true) }))
    const { router } = open('/admin/patient/5?views=1')
    await screen.findByText('ascunde accesările')
    await tabTo('Plan și plăți')
    expect(router.state.location.search).toBe('?tab=plan&views=1')
    await tabTo('Date pacient')
    expect(router.state.location.search).toBe('?tab=date&views=1')
    fireEvent.click(screen.getByText('Arhivează pacientul'))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/patients/5/archive?views=1', { on: true }))
    /* переключатель ленты снимает views и не трогает вкладку; обратно — Rezumat без query */
    await tabTo('Rezumat')
    expect(router.state.location.search).toBe('?views=1')
    fireEvent.click(screen.getByText('ascunde accesările'))
    await waitFor(() => expect(router.state.location.search).toBe(''))
    expect(opens()).toBe(1)
  })

  it('B6 быстрые действия ведут на вкладки; зуб из плана открывает одонтограмму с этим зубом', async () => {
    serve()
    const { router } = open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('Plan de tratament'))
    await strip().findByRole('tab', { name: 'Plan și plăți', selected: true })
    expect(router.state.location.search).toBe('?tab=plan')
    fireEvent.click(rowOf('Coroană 11').querySelector('button.pt') as HTMLElement)
    await strip().findByRole('tab', { name: 'Odontogramă', selected: true })
    await odoReady()
    /* зуб выбран в инспекторе рабочего стола и в фокусе — клавиатура готова */
    await waitFor(() => expect((document.querySelector('.insp-n b') as HTMLElement).textContent).toBe('11'))
    expect((document.activeElement as HTMLElement).dataset.n).toBe('11')
    /* всё это — переходы одного адреса: фиша открыта один раз */
    expect(opens()).toBe(1)
    /* «Încarcă document» → Documente; «Notiță» → Date pacient с раскрытой формой */
    await tabTo('Rezumat')
    fireEvent.click(screen.getByText('Încarcă document'))
    await strip().findByRole('tab', { name: 'Documente', selected: true })
    await tabTo('Rezumat')
    fireEvent.click(screen.getByText('Notiță'))
    await strip().findByRole('tab', { name: 'Date pacient', selected: true })
    expect((document.querySelector('.dp-pedit') as HTMLElement).style.display).toBe('flex')
  })

  it('B6 клавиатура: ← → Home End ходят по вкладкам по кругу, фокус идёт следом', async () => {
    serve()
    const { router } = open()
    await screen.findByText('Pin Test', { selector: 'h2' })
    const list = screen.getByRole('tablist', { name: 'Secțiunile fișei' })
    expect(strip().getAllByRole('tab').map((x) => x.tabIndex)).toEqual([0, -1, -1, -1, -1, -1, -1])
    fireEvent.keyDown(list, { key: 'ArrowRight' })
    await strip().findByRole('tab', { name: 'Odontogramă', selected: true })
    expect(document.activeElement?.textContent).toBe('Odontogramă')
    expect(router.state.location.search).toBe('?tab=odonto')
    fireEvent.keyDown(list, { key: 'End' })
    await strip().findByRole('tab', { name: 'Date pacient', selected: true })
    fireEvent.keyDown(list, { key: 'ArrowRight' })
    await strip().findByRole('tab', { name: 'Rezumat', selected: true })
    expect(router.state.location.search).toBe('')
    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    await strip().findByRole('tab', { name: 'Date pacient', selected: true })
    fireEvent.keyDown(list, { key: 'Home' })
    await strip().findByRole('tab', { name: 'Rezumat', selected: true })
    expect(document.activeElement?.textContent).toBe('Rezumat')
    expect(strip().getAllByRole('tab').map((x) => x.tabIndex)).toEqual([0, -1, -1, -1, -1, -1, -1])
  })

  it('B6 вкладка Parodontogramă: лист грузит себя сам по осмотру из адреса; смена осмотра и новый осмотр — адресом', async () => {
    serve()
    const { router } = open('/admin/patient/5?tab=perio&exam=4')
    await screen.findByText('Pin Test', { selector: 'h2' })
    /* осмотр из адреса — в запрос; фиша не перечитывалась */
    await waitFor(() => expect(document.querySelector('.ptooth[data-tooth="16"]')).toBeTruthy())
    expect(get).toHaveBeenCalledWith('/patients/5/perio?exam=4', expect.anything())
    expect(opens()).toBe(1)
    expect(screen.getByText('Pe tot ecranul').closest('a')?.getAttribute('href')).toBe('/admin/patient/5/parodontograma?exam=4')
    expect(screen.queryByText('Odontogramă', { selector: '.odo-more' })).toBeNull()
    /* выбор другого осмотра — адрес (replace), лист снят на время ответа, потом новый запрос */
    const gets = () => get.mock.calls.filter(([p]) => String(p).startsWith('/patients/5/perio')).length
    const before = gets()
    fireEvent.change(screen.getByLabelText('Examen'), { target: { value: '9' } })
    await waitFor(() => expect(router.state.location.search).toBe('?tab=perio&exam=9'))
    await waitFor(() => expect(gets()).toBe(before + 1))
    expect(get).toHaveBeenLastCalledWith('/patients/5/perio?exam=9', expect.anything())
    await waitFor(() => expect(document.querySelector('.ptooth[data-tooth="16"]')).toBeTruthy())
    /* новый осмотр: ответ POST уже на экране, адрес ведёт к нему БЕЗ нового GET */
    const made = { ...PERIO, exams: [{ ...PEXAM, id: 12, teeth: 0 }, ...PERIO.exams], exam: { ...PEXAM, id: 12, teeth: 0 }, rows: {} }
    post.mockResolvedValueOnce(ok(made, 'ok_perio_new', 'Examen nou'))
    const after = gets()
    fireEvent.click(screen.getByText('Examen nou'))
    await waitFor(() => expect(router.state.location.search).toBe('?tab=perio&exam=12'))
    expect(post).toHaveBeenCalledWith('/patients/5/perio/exams', expect.anything())
    expect(gets()).toBe(after)
    expect(opens()).toBe(1)
    /* другая вкладка снимает лист и осмотр из адреса; обратно — свежий */
    await tabTo('Odontogramă')
    expect(router.state.location.search).toBe('?tab=odonto')
    expect(document.querySelector('.perio')).toBeNull()
    fireEvent.click(screen.getByText('Parodontogramă', { selector: '.odo-more' }))
    await strip().findByRole('tab', { name: 'Parodontogramă', selected: true })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/patients/5/perio', expect.anything()))
  })

  it('B6 вкладка Vizite: дневник визита открывается на месте, визит в адресе; запись без нового открытия фиши; закрытие — история', async () => {
    serve()
    post.mockResolvedValueOnce(ok({ ...VPAGE, record: { acuze: 'Durere nouă', examen: '', diagnostic: '', tratament: '', recomandari: '',
      created: '26.09.2026 14:00', updated: '', author: 'Director' } }, 'ok_visit', 'Consultația a fost salvată'))
    const { router } = open('/admin/patient/5?tab=vizite')
    await screen.findByText('Pin Test', { selector: 'h2' })
    fireEvent.click(screen.getByText('+ Consultație'))
    await waitFor(() => expect(router.state.location.search).toBe('?tab=vizite&visit=3'))
    expect(await screen.findByText('Jurnalul consultației')).toBeTruthy()
    const back = encodeURIComponent('/admin/patient/5?tab=vizite')
    expect(get).toHaveBeenCalledWith(`/visits/3?back=${back}`, expect.anything())
    expect(opens()).toBe(1)
    /* имя пациента — текстом (мы уже в его фише), история и ближайший визит сняты */
    expect(screen.queryByText('Istoric vizite')).toBeNull()
    expect(document.querySelector('.frow .v a')).toBeNull()
    fireEvent.change(screen.getByLabelText('Acuze / motivul prezentării'), { target: { value: 'Durere nouă' } })
    fireEvent.click(screen.getByText('Salvează consultația'))
    expect(await screen.findByText('Consultația a fost salvată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/visits/3', expect.objectContaining({ acuze: 'Durere nouă', done: [], back: '/admin/patient/5?tab=vizite' }))
    expect(screen.getByText(/Înregistrat: 26.09.2026 14:00/)).toBeTruthy()
    expect(opens()).toBe(1)
    /* «Pe tot ecranul» — прежняя страница дневника с возвратом сюда */
    expect(screen.getByText('Pe tot ecranul').closest('a')?.getAttribute('href')).toBe(`/admin/visit/3?back=${back}`)
    /* закрытие — история визитов, адрес без визита; F5 на адресе дневника — снова дневник */
    fireEvent.click(screen.getByText('Vizite', { selector: '.dp-vnav button' }))
    await waitFor(() => expect(router.state.location.search).toBe('?tab=vizite'))
    expect(screen.getByText('Istoric vizite')).toBeTruthy()
    expect(screen.queryByText('Jurnalul consultației')).toBeNull()
    fireEvent.click(screen.getByText('+ Consultație'))
    await waitFor(() => expect(router.state.location.search).toBe('?tab=vizite&visit=3'))
    const r2 = reopen(router)
    expect(await screen.findByText('Jurnalul consultației')).toBeTruthy()
    expect(r2.router.state.location.search).toBe('?tab=vizite&visit=3')
    expect(opens()).toBe(1)
  })

  /* ---- 01.10: риски в шапке, «Anamneză» рядом с 043/e, черновик, «назад» с листов ---- */

  it('шапка: полоса рисков — предупреждения и анамнез одной строкой, на всех вкладках', async () => {
    serve()
    open()
    await settled()
    const risk = () => screen.getByRole('note', { name: 'Riscuri medicale' })
    expect(risk().textContent).toContain('Alergie: Penicilină')
    expect(risk().textContent).toContain('Diabet zaharat')
    expect(risk().textContent).toContain('Alergii: latex')
    await tabTo('Plan și plăți')
    expect(risk().textContent).toContain('Alergii: latex')
  })

  it('шапка: без рисков полосы нет; анамнез не собирали — мягкое напоминание с кнопкой', async () => {
    serve({ ...CARD, alerts: [], anamneza: { ...CARD.anamneza, state: 'ok', n_risk: 0, marked: [], free: [] } })
    open()
    await settled()
    expect(screen.queryByRole('note', { name: 'Riscuri medicale' })).toBeNull()
    cleanup()
    serve({ ...CARD, alerts: [], anamneza: { ...CARD.anamneza, filled: false, state: 'none', n_risk: 0, marked: [], free: [] } })
    open()
    await settled()
    const note = screen.getByRole('note', { name: 'Riscuri medicale' })
    expect(note.className).toContain('soft')
    fireEvent.click(within(note).getByRole('button', { name: /Completează/ }))
    await strip().findByRole('tab', { name: 'Date pacient', selected: true })
  })

  it('«Anamneză» в шапке открывает Date pacient; печатные листы несут «назад» на текущую вкладку', async () => {
    serve()
    open()
    await settled()
    const fisa = () => screen.getByRole('link', { name: /Fișa 043\/e/ }) as HTMLAnchorElement
    expect(fisa().getAttribute('href')).toBe('/admin/patient/5/fisa043?back=%2Fadmin%2Fpatient%2F5')
    fireEvent.click(screen.getByRole('button', { name: /^Anamneză$/ }))
    await strip().findByRole('tab', { name: 'Date pacient', selected: true })
    expect((document.querySelector('details.anform') as HTMLDetailsElement).open).toBe(true)
    expect(fisa().getAttribute('href')).toBe('/admin/patient/5/fisa043?back=%2Fadmin%2Fpatient%2F5%3Ftab%3Ddate')
    expect((screen.getByRole('link', { name: /Formular pentru pacient/ }) as HTMLAnchorElement).getAttribute('href'))
      .toBe('/admin/patient/5/anamneza/print?back=%2Fadmin%2Fpatient%2F5%3Ftab%3Ddate')
    expect((screen.getByRole('link', { name: /Informare \/ acord/ }) as HTMLAnchorElement).getAttribute('href'))
      .toBe('/admin/patient/5/acord?back=%2Fadmin%2Fpatient%2F5%3Ftab%3Ddate')
    await tabTo('Plan și plăți')
    expect((within(screen.getByRole('note', { name: 'Acord informat' })).getByRole('link') as HTMLAnchorElement).getAttribute('href'))
      .toBe('/admin/patient/5/plan-acord?back=%2Fadmin%2Fpatient%2F5%3Ftab%3Dplan')
  })

  /* ---- 01.10: Documente — центр бумаг, план уровня 1 ---- */

  it('Documente: бланки со статусом над файлами; «Încarcă semnat» выбирает категорию', async () => {
    serve()
    open()
    await settled()
    await tabTo('Documente')
    const form = (key: string) => document.querySelector(`.dp-form[data-form="${key}"]`) as HTMLElement
    expect(form('acord_plan').textContent).toContain('2 proceduri · 1 900 MDL')
    expect(form('acord_plan').textContent).toContain('tipărit 18.09.2026')
    expect(form('acord_plan').textContent).toContain('nesemnat')
    expect(form('chestionar').textContent).toContain('completat în program 18.09.2026')
    expect(form('acord195').textContent).toContain('netipărit')
    /* у 043/e подписи нет — только печать */
    expect(within(form('fisa043')).queryByRole('button', { name: /Încarcă semnat/ })).toBeNull()
    expect((within(form('acord195')).getByRole('link', { name: /Tipărește/ }) as HTMLAnchorElement).getAttribute('href'))
      .toBe('/admin/patient/5/acord?back=%2Fadmin%2Fpatient%2F5%3Ftab%3Ddocs')
    fireEvent.click(within(form('acord_plan')).getByRole('button', { name: /Încarcă semnat/ }))
    expect((screen.getByLabelText('Categorie') as HTMLSelectElement).value).toBe('acord_plan')
    /* подпись к файлу — категория */
    expect(screen.getByText('Radiografie', { selector: '.dcat' })).toBeTruthy()
  })

  it('Documente: подписанный скан — зелёная отметка, открывается просмотрщиком; план изменён после подписи — предупреждение', async () => {
    const signed = {
      ...CARD,
      documents: [{ id: 9, filename: 'acord-semnat.png', when: '19.09.2026', size: '0 KB', mime: 'image/png', category: 'acord_plan', category_label: 'Acord informat la plan — semnat', icon: 'clipboard', view: 'img' as const }, ...CARD.documents],
      forms: CARD.forms.map((f) => f.key === 'acord_plan' ? { ...f, signed: { doc_id: 9, when: '19.09.2026' }, stale: true } : f),
    }
    serve(signed)
    open()
    await settled()
    await tabTo('Documente')
    const form = document.querySelector('.dp-form[data-form="acord_plan"]') as HTMLElement
    expect(form.textContent).toContain('semnat 19.09.2026')
    expect(form.textContent).toContain('plan modificat după semnare')
    fireEvent.click(within(form).getByRole('button', { name: /semnat 19.09.2026/ }))
    /* `#docs dialog`: у шапки свой dialog.wide (окна KPI) */
    await waitFor(() => expect((document.querySelector('#docs dialog.wide') as HTMLDialogElement).open).toBe(true))
    expect(document.querySelector('.dvbody img')?.getAttribute('src')).toBe('/admin/doc/9?inline=1')
  })

  it('план уровня 1: шапка колонок, одна кнопка на строку, отказ и удаление в меню, полоса согласия ведёт в Documente', async () => {
    serve()
    open()
    await settled()
    await tabTo('Plan și plăți')
    expect(document.querySelector('.plan-head')?.textContent).toBe('DinteProcedurăMedicTermenStarePreț')
    const row = rowOf('Extracție 48')
    expect(within(row).getAllByRole('button').map((b) => b.textContent?.trim())).toEqual(['48', 'Începe', ''])
    expect(within(row).queryByRole('button', { name: /Refuz/ })).toBeNull()
    fireEvent.click(within(row).getByRole('button', { name: /Mai multe acțiuni/ }))
    const menu = screen.getByRole('menu', { name: 'Extracție 48' })
    expect(within(menu).getAllByRole('menuitem').map((b) => b.textContent?.trim())).toEqual(['Refuz', 'Șterge din plan'])
    /* у начатой позиции удаления нет — только отказ */
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
    fireEvent.click(within(rowOf('Coroană 11')).getByRole('button', { name: /Mai multe acțiuni/ }))
    expect(within(screen.getByRole('menu', { name: 'Coroană 11' })).getAllByRole('menuitem').map((b) => b.textContent?.trim())).toEqual(['Refuz'])
    fireEvent.keyDown(document, { key: 'Escape' })
    /* полоса согласия: напечатан, не подписан → «Încarcă exemplarul semnat» ведёт в Documente с категорией */
    const note = screen.getByRole('note', { name: 'Acord informat' })
    expect(note.textContent).toContain('tipărit 18.09.2026')
    fireEvent.click(within(note).getByRole('button', { name: /Încarcă exemplarul semnat/ }))
    await strip().findByRole('tab', { name: 'Documente', selected: true })
    expect((screen.getByLabelText('Categorie') as HTMLSelectElement).value).toBe('acord_plan')
  })

  it('Documente: «Scanează semnat» — лист за листом в сессию, «Salvează» кладёт PDF с категорией бланка', async () => {
    serve()
    post.mockImplementation((path: string) => {
      if (path === '/patients/5/scan/page') return Promise.resolve(ok({ pages: post.mock.calls.filter(([p]) => p === '/patients/5/scan/page').length, previews: ['data:image/png;base64,AAAA'] }))
      if (path === '/patients/5/scan/finish') return Promise.resolve(ok({ ...CARD, forms: CARD.forms.map((f) => f.key === 'acord_plan' ? { ...f, signed: { doc_id: 9, when: '01.10.2026' } } : f) }, 'ok_scan', 'Document scanat și salvat în fișă'))
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    open()
    await settled()
    await tabTo('Documente')
    expect(await screen.findByText(/Scaner: Scaner de test/)).toBeTruthy()
    const form = document.querySelector('.dp-form[data-form="acord_plan"]') as HTMLElement
    fireEvent.click(within(form).getByRole('button', { name: /Scanează semnat/ }))
    /* первый лист — сразу, без второго щелчка */
    await waitFor(() => expect(post).toHaveBeenCalledWith('/patients/5/scan/page', {}))
    const box = await screen.findByRole('region', { name: 'Scanare' })
    expect(box.textContent).toContain('Acord informat la plan — semnat')
    await waitFor(() => expect(box.textContent).toContain('1 pagină'))
    fireEvent.click(within(box).getByRole('button', { name: /Încă o pagină/ }))
    await waitFor(() => expect(box.textContent).toContain('2 pagini'))
    fireEvent.click(within(box).getByRole('button', { name: /Salvează în fișă/ }))
    expect(await screen.findByText('Document scanat și salvat în fișă')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/scan/finish', { category: 'acord_plan', title: 'Acord informat la planul de tratament' })
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Scanare' })).toBeNull())
    expect((document.querySelector('.dp-form[data-form="acord_plan"]') as HTMLElement).textContent).toContain('semnat 01.10.2026')
  })

  it('Documente: без сканера кнопок сканирования нет, подпись говорит, что его нет', async () => {
    serve()
    get.mockImplementation((path: string) => {
      if (path === '/scan/status') return Promise.resolve(ok({ ok: false, name: '' }))
      if (path === '/patients/5') return Promise.resolve(ok(CARD))
      if (path === '/patients/5/odontogram') return Promise.resolve(ok(ODO))
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    open()
    await settled()
    await tabTo('Documente')
    expect(await screen.findByText(/niciun scaner găsit/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Scanează/ })).toBeNull()
  })

  it('план: «Finalizează» с ценой спрашивает и называет сумму, которая входит в сольд; отказ не шлёт', async () => {
    serve()
    open()
    await settled()
    await tabTo('Plan și plăți')
    const ask = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    fireEvent.click(within(rowOf('Coroană 11')).getByRole('button', { name: /Finalizează/ }))
    await waitFor(() => expect(ask).toHaveBeenCalledWith(expect.stringContaining('1 200 MDL intră în soldul')))
    expect(post).not.toHaveBeenCalled()
    ask.mockReturnValueOnce(true)
    post.mockResolvedValueOnce(ok(CARD, 'ok_card', 'Fișa pacientului a fost actualizată'))
    fireEvent.click(within(rowOf('Coroană 11')).getByRole('button', { name: /Finalizează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/patients/5/plan/1/status', { to: 'finalizat', motiv: '' }))
  })

  it('зуб → план из вкладки Odontogramă (01.10): позиция уходит на маршрут плана в режиме ленты, свежая фиша — из ответа, не новым открытием', async () => {
    const added: PatientCard = {
      ...CARD,
      plan: {
        ...CARD.plan, n_act: 3, total: 4900,
        items: [
          { id: 9, tooth: 11, procedure: 'Coroană zirconiu', doctor: 'Dr. Activ Doi', status: 'planificat', label: 'Planificat', price: 3000, due: '', overdue: false, done: '', motiv: '', next: 'in_lucru', refusable: true, deletable: true },
          ...CARD.plan.items,
        ],
      },
    }
    serve()
    post.mockResolvedValueOnce(ok({ ...added, activity: feed(added, true) }, 'ok_card', 'Fișa pacientului a fost actualizată'))
    open('/admin/patient/5?tab=odonto&views=1')
    await odoReady()
    fireEvent.click(document.querySelector('#odo .tooth-btn[data-n="11"]') as HTMLElement)
    const insp = document.querySelector('.insp') as HTMLElement
    fireEvent.click(within(insp).getByRole('button', { name: 'Adaugă în plan' }))
    const dlg = document.querySelector('dialog.dp-plan-dlg') as HTMLDialogElement
    expect(dlg.hasAttribute('open')).toBe(true)
    expect(dlg.isConnected).toBe(true)
    fireEvent.change(within(dlg).getByLabelText('Procedură (ex. Coroană zirconiu)'), { target: { value: 'Coroană zirconiu' } })
    /* врачи диалога — из модели одонтограммы (у зуба 11 врача нет — список пуст по умолчанию) */
    expect((within(dlg).getByLabelText('Medic —') as HTMLSelectElement).value).toBe('')
    expect(document.activeElement).toBe(within(dlg).getByLabelText('Procedură (ex. Coroană zirconiu)'))
    fireEvent.change(within(dlg).getByLabelText('Medic —'), { target: { value: 'Dr. Activ Doi' } })
    fireEvent.change(within(dlg).getByLabelText('Preț MDL'), { target: { value: '3000' } })
    fireEvent.click(within(dlg).getByRole('button', { name: 'Adaugă în plan' }))
    expect(await screen.findByText('Fișa pacientului a fost actualizată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/plan?views=1', {
      tooth: '11', procedure: 'Coroană zirconiu', doctor: 'Dr. Activ Doi', price: '3000', due_date: '',
    })
    /* диалог закрывает эффект — после коммита плашки, поэтому ждём */
    await waitFor(() => expect(dlg.hasAttribute('open')).toBe(false))
    expect(opens()).toBe(1)
    /* фиша из ответа — план уже с позицией; дуга НЕ перечитана и не перемонтирована:
       тот же узел, выбранный зуб на месте, ожидания не было */
    expect(get.mock.calls.filter(([p]) => p === '/patients/5/odontogram').length).toBe(1)
    expect(dlg.isConnected).toBe(true)
    expect(document.querySelector('.dp-odo-wait')).toBeNull()
    expect(document.querySelector('#odo .tooth-btn[data-n="11"]')?.className).toContain('sel')
    await tabTo('Plan și plăți')
    expect(rowOf('Coroană zirconiu').querySelector('.pt')?.textContent).toBe('11')
  })

  it('анамнез: черновик переживает смену вкладки, вкладка помечена, уход с фиши спрашивает', async () => {
    serve()
    const { router } = open()
    await settled()
    await tabTo('Date pacient')
    const diabet = () => screen.getByLabelText('Diabet zaharat') as HTMLInputElement
    expect(diabet().checked).toBe(true)
    fireEvent.click(diabet())
    expect(diabet().checked).toBe(false)
    expect(screen.getByText('modificări nesalvate')).toBeTruthy()
    await tabTo('Rezumat')
    expect(strip().getByRole('tab', { name: /Date pacient/ }).querySelector('.wtab-dot')).toBeTruthy()
    await tabTo('Date pacient')
    /* до 01.10 вкладка размонтировалась и галочка возвращалась к сохранённой */
    expect(diabet().checked).toBe(false)
    /* уход с фиши — вопрос; отказ оставляет на месте */
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    fireEvent.click(screen.getByRole('link', { name: /Pacienți/ }))
    await waitFor(() => expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('nesalvate')))
    expect(router.state.location.pathname).toBe('/admin/patient/5')
    expect(diabet().checked).toBe(false)
    /* сохранили — свежая фиша, черновика нет, точки нет */
    post.mockResolvedValueOnce(ok({ ...CARD, anamneza: { ...CARD.anamneza, flags: ['cardio'] } }, 'ok_anam', 'Anamneza a fost salvată'))
    fireEvent.click(screen.getByRole('button', { name: /Salvează anamneza/ }))
    expect(await screen.findByText('Anamneza a fost salvată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/anamneza', expect.objectContaining({ flags: ['cardio'] }))
    expect(screen.queryByText('modificări nesalvate')).toBeNull()
    expect(strip().getByRole('tab', { name: /Date pacient/ }).querySelector('.wtab-dot')).toBeNull()
  })
})
