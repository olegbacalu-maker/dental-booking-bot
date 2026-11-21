import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { openScreen } from '../../test/openScreen'
import { ImportScreen, loadPimport } from './ImportScreen'
import {
  assign, chooseDoctor, hasName, hasVisits, num, type PiCheck, type PiDoctor, type PiGroup, type PiHome, type PiImport,
  type PiRow, type PiRun, type PiUndo, type PiVisits,
} from './pimport'

/* Импорт пациентов: файл телом запроса, шаг колонок с угаданным выбором,
   проверка со словами сервера, запись порциями с продолжением после обрыва,
   итог с отчётом, прошлые импорты и отмена; из сети — слова сервера без кнопок. */

const { get, post, postRaw, download, saveBlob } = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), postRaw: vi.fn(), download: vi.fn(), saveBlob: vi.fn(),
}))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postRaw, download }, loginUrl: () => '/admin/login?next=x' }
})
vi.mock('./pimport', async (importOriginal) => ({ ...await importOriginal<typeof import('./pimport')>(), saveBlob }))

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const RUN: PiImport = { id: 3, at: '12.11.2026 14:44', actor: 'Ana R', file: 'pacienti.xlsx', rows: 200,
  created: 180, filled: 0, skipped: 20, removed: 0, visits: 0, visits_past: 0, visits_skipped: 0, visits_removed: 0,
  undone: false, can_undo: true }

function home(over: Partial<PiHome> = {}): PiHome {
  return {
    imports: [],
    fields: [{ id: '', label: 'Nu importa' }, { id: 'full', label: 'Nume și prenume' }, { id: 'last', label: 'Nume (familie)' },
      { id: 'first', label: 'Prenume' }, { id: 'phone', label: 'Telefon' }, { id: 'phone2', label: 'Telefon 2' },
      { id: 'birth', label: 'Data nașterii' }, { id: 'notes', label: 'Notițe' }],
    limits: { bytes: 10485760, rows: 20000, batch: 200 },
    encodings: ['utf-8', 'utf-16', 'cp1250', 'cp1251'], delimiters: [';', ',', '\t', '|'],
    remote: null,
    ...over,
  }
}

function prow(over: Partial<PiRow> = {}): PiRow {
  return { line: 2, name: 'Ana Test', phone: '069111222', birth: '01.01.1950', idnp: '', reason: '', notes: [],
    match: null, forceable: false, fill: [], ...over }
}

const GROUPS: PiGroup[] = [
  { id: 'new', label: 'Fișe noi', count: 398, more: 98, rows: [prow()] },
  { id: 'noted', label: 'Cu observații', count: 2, more: 0,
    rows: [prow({ line: 3, name: '<img src=x onerror=alert(1)>', notes: ['cifra de control a IDNP nu corespunde, verificați'] })] },
  { id: 'exists', label: 'Există deja', count: 2, more: 0, rows: [
    prow({ line: 4, name: 'Ion Vechi', reason: 'există deja (același telefon și nume): Ion Vechi',
      match: { id: 41, name: 'Ion Vechi' }, fill: ['adresă', 'e-mail'] }),
    prow({ line: 5, name: 'Maria Posibil', reason: 'posibil există deja (același nume și dată a nașterii): Maria Posibil',
      match: { id: 42, name: 'Maria Posibil' }, forceable: true })] },
  { id: 'dup', label: 'Dubluri în fișier', count: 0, more: 0, rows: [] },
  { id: 'bad', label: 'Nu intră', count: 1, more: 0, rows: [prow({ line: 9, name: '', reason: 'lipsește numele' })] },
]

function checked(over: Partial<PiCheck> = {}): PiCheck {
  return {
    file: { name: 'pacienti.xlsx', kind: 'xlsx', size: 16212, sheets: [{ name: 'Pacienți', rows: 404 }], enc: '', delim: '' },
    opts: { sheet: 0, header: 1, cols: { 1: 'full', 2: 'birth', 3: 'phone' }, enc: '', delim: '', fill: false, force: [], docs: {},
      past: true, sms: false, svc: 'consult' },
    columns: [{ index: 0, letter: 'A', title: 'ID', field: '' }, { index: 1, letter: 'B', title: 'Nume și prenume', field: 'full' },
      { index: 2, letter: 'C', title: 'Data nașterii', field: 'birth' }, { index: 3, letter: 'D', title: 'Telefon', field: 'phone' }],
    preview: [{ line: 2, cells: ['1', 'Ana Test', '01.01.1950', '069111222'] },
      { line: 3, cells: ['2', '<b>Ion</b>', '', ''] }],
    doctors: [], clinic_doctors: [],
    ready: true,
    counts: { rows: 403, create: 400, new: 398, noted: 2, exists: 2, dup: 0, bad: 1, fill: 1, family: 3 },
    groups: GROUPS, token: 'tok32', parts: 3,
    visits: null, services: [], sms_on: false,
    ...over,
  }
}

const FILE = new File(['PK-demo'], 'pacienti.xlsx')
const paramsOf = (path: string) => new URLSearchParams(path.split('?')[1])
const optsOf = (path: string) => JSON.parse(paramsOf(path).get('opts') ?? '{}') as Record<string, unknown>
const lastRaw = () => postRaw.mock.calls.at(-1) as [string, File]

async function open(data: PiHome = home(), navigate = vi.fn()) {
  get.mockResolvedValue(ok(data))
  const view = openScreen('/admin/patients/import', '/admin/patients/import', <ImportScreen navigate={navigate} />, loadPimport)
  await waitFor(() => expect(document.querySelector('.pi')).not.toBeNull())
  return { ...view, navigate }
}

function pick(file: File = FILE) {
  fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } })
}

async function toCols(c: PiCheck = checked()) {
  postRaw.mockResolvedValue(ok(c))
  pick()
  await waitFor(() => expect(document.querySelector('.pi-preview')).not.toBeNull())
}

async function toCheck(c: PiCheck = checked()) {
  await toCols(c)
  fireEvent.click(screen.getByRole('button', { name: /Verifică/ }))
  await waitFor(() => expect(document.querySelector('.pi-counts')).not.toBeNull())
}

const colSelect = (letter: string) => screen.getByLabelText(`Ce conține coloana ${letter}`) as HTMLSelectElement
const stepNow = () => document.querySelector('.pi-steps [aria-current="step"]')?.textContent?.replace(/^\d+\s*/, '')
const runReply = (part: number, done: boolean, total: PiImport = RUN, more: Partial<PiRun> = {}) => ok(
  { import: 3, part, parts: 3, done, created: 200, filled: 0, skipped: 0, visits: 0, visits_past: 0, visits_skipped: 0,
    recall: 0, total, ...more }, done ? 'pi_done' : '', done ? 'Import finalizat' : '')

const undoReply = (over: Partial<PiUndo>, code = '', text = '') => ok<PiUndo>(
  { done: false, phase: 'p', after: 0, removed: 0, visits_removed: 0, kept: 0, visits_kept: 0, total: RUN, ...over }, code, text)

const VISITS: PiVisits = {
  counts: { v_new: 5, v_past: 1, v_no: 2, rows: 8 },
  groups: [
    { id: 'v_new', label: 'Programări noi', count: 5, more: 0, rows: [
      { line: 2, name: 'Ana Test', when: '24.11.2026 09:00', doctor: 'Dr. Activ Doi', service: 'Consultație', reason: '',
        notes: [], patient: null }] },
    { id: 'v_past', label: 'Vizite trecute (istoric)', count: 1, more: 0, rows: [
      { line: 5, name: 'Ion Vechi', when: '05.05.2026 10:00', doctor: 'Dr. Activ Trei', service: 'Igienizare', reason: '',
        notes: ['programarea se adaugă la fișa existentă: Ion Vechi'], patient: 41 }] },
    { id: 'v_no', label: 'Nu se programează', count: 2, more: 0, rows: [
      { line: 3, name: 'Fara Ora', when: '24.11.2026', doctor: 'Activ Trei', service: '', reason:
        'programare fără oră — data trecută în notițe', notes: [], patient: null },
      { line: 4, name: 'Ocupat Om', when: '24.11.2026 09:30', doctor: 'Dr. Activ Doi', service: 'Consultație',
        reason: 'ocupat — rândul 2 are programare la același medic în acest timp', notes: [], patient: null }] },
  ],
}

const SERVICES = [{ id: 'consult', name: 'Consultație' }, { id: 'hygiene', name: 'Igienizare' }]

function withVisits(over: Partial<PiCheck> = {}): PiCheck {
  const base = checked()
  return checked({ visits: VISITS, services: SERVICES,
    opts: { ...base.opts, cols: { ...base.opts.cols, 4: 'appt', 5: 'appt_time', 6: 'doctor' } }, ...over })
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('ImportScreen: шаг «Fișier»', () => {
  it('выбор файла, модель ссылкой, подсказка свёрнута, прошлых импортов нет', async () => {
    await open()
    expect(stepNow()).toBe('Fișier')
    expect(screen.getByRole('button', { name: /Alege fișierul/ })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Descarcă modelul' }).getAttribute('href')).toBe('/api/pimport/model.xlsx')
    expect((document.querySelector('.pi-how') as HTMLDetailsElement).open).toBe(false)
    expect(document.body.textContent).toContain('cel mult 10 MB și 20 000 de rânduri')
    expect(document.body.textContent).toContain('încă nu s-a făcut niciun import')
  })

  it('из сети: слова сервера вместо выбора файла и без кнопок отмены', async () => {
    await open(home({ imports: [RUN], remote: { code: 'only_local', tone: 'warn', text: 'Doar pe calculatorul principal al clinicii' } }))
    expect(screen.getByRole('status').textContent).toBe('Doar pe calculatorul principal al clinicii')
    expect(screen.queryByRole('button', { name: /Alege fișierul/ })).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeNull()
    expect(screen.queryByRole('button', { name: /Anulează importul/ })).toBeNull()
    expect(document.body.textContent).toContain('pacienti.xlsx')
  })

  it('файл больше потолка не отправляется: отказ словом', async () => {
    await open(home({ limits: { bytes: 4, rows: 20000, batch: 200 } }))
    pick()
    expect(await screen.findByText(/Fișierul este prea mare/)).toBeTruthy()
    expect(postRaw).not.toHaveBeenCalled()
  })

  it('.xls — отказ словами сервера, шаг остаётся первым', async () => {
    await open()
    postRaw.mockRejectedValue(new ApiError(
      { kind: 'validation', code: 'pi_old_xls', text: 'Fișier Excel vechi (.xls) — salvați ca .xlsx' }, 'x'))
    pick(new File(['x'], 'vechi.xls'))
    expect(await screen.findByText('Fișier Excel vechi (.xls) — salvați ca .xlsx')).toBeTruthy()
    expect(stepNow()).toBe('Fișier')
  })

  it('файл уходит телом запроса, имя и пустой выбор — в адресе', async () => {
    await open()
    await toCols()
    const [path, body] = lastRaw()
    expect(path.startsWith('/pimport/check?')).toBe(true)
    expect(paramsOf(path).get('name')).toBe('pacienti.xlsx')
    expect(optsOf(path)).toEqual({})
    expect(body).toBe(FILE)
    expect(stepNow()).toBe('Coloane')
  })

  it('401 при чтении файла — уход на вход', async () => {
    const { navigate } = await open()
    postRaw.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'x'))
    pick()
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})

describe('ImportScreen: шаг «Coloane»', () => {
  it('над каждой колонкой — список с угаданным значением; строки файла — текстом', async () => {
    await open()
    await toCols()
    expect(['A', 'B', 'C', 'D'].map((x) => colSelect(x).value)).toEqual(['', 'full', 'birth', 'phone'])
    expect(document.querySelector('.pi-preview thead')?.textContent).toContain('B · Nume și prenume')
    expect(document.querySelector('.pi-preview tbody')?.textContent).toContain('<b>Ion</b>')
    expect(document.querySelector('.pi-preview b')).toBeNull()
    expect(screen.queryByText('Foaia')).toBeNull()
    expect(screen.queryByText('Codificarea')).toBeNull()
  })

  it('одиночное поле переезжает с прежней колонки; без имени «Verifică» выключена со словом', async () => {
    await open()
    await toCols()
    fireEvent.change(colSelect('A'), { target: { value: 'full' } })
    expect([colSelect('A').value, colSelect('B').value]).toEqual(['full', ''])
    fireEvent.change(colSelect('A'), { target: { value: '' } })
    expect((screen.getByRole('button', { name: /Verifică/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('note').textContent).toBe('Alegeți coloana cu numele pacientului.')
  })

  it('несколько листов — выбор листа; смена листа перечитывает файл без прежних колонок', async () => {
    await open()
    await toCols(checked({ file: { ...checked().file, sheets: [{ name: 'Pacienți', rows: 404 }, { name: 'Arhivă', rows: 12 }] } }))
    fireEvent.change(screen.getByLabelText('Foaia'), { target: { value: '1' } })
    await waitFor(() => expect(optsOf(lastRaw()[0]).sheet).toBe(1))
    expect(optsOf(lastRaw()[0])).not.toHaveProperty('cols')
    expect(optsOf(lastRaw()[0])).not.toHaveProperty('header')
  })

  it('CSV: кодировка и разделитель; смена кодировки перечитывает файл', async () => {
    await open()
    await toCols(checked({ file: { ...checked().file, kind: 'csv', enc: 'cp1251', delim: ';' },
      opts: { ...checked().opts, enc: 'cp1251', delim: ';' } }))
    expect((screen.getByLabelText('Codificarea') as HTMLSelectElement).value).toBe('cp1251')
    expect(within(screen.getByLabelText('Separatorul')).getByText('tab')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Codificarea'), { target: { value: 'cp1250' } })
    await waitFor(() => expect(optsOf(lastRaw()[0]).enc).toBe('cp1250'))
    expect(optsOf(lastRaw()[0]).delim).toBe(';')
  })

  it('«Verifică» шлёт выбор человека целиком; без имени сервер оставляет на шаге колонок', async () => {
    await open()
    await toCols()
    fireEvent.change(colSelect('A'), { target: { value: 'notes' } })
    postRaw.mockResolvedValue(ok(checked({ ready: false, counts: null, groups: [], token: '' })))
    fireEvent.click(screen.getByRole('button', { name: /Verifică/ }))
    await waitFor(() => expect(optsOf(lastRaw()[0]).cols).toEqual({ 0: 'notes', 1: 'full', 2: 'birth', 3: 'phone' }))
    expect(optsOf(lastRaw()[0]).header).toBe(1)
    await waitFor(() => expect(postRaw).toHaveBeenCalledTimes(2))
    expect(stepNow()).toBe('Coloane')
  })
})

const CLINIC = [{ id: 'd1', name: 'Dr. Elena Rusu', active: true }, { id: 'd2', name: 'Dr. Ion Rusu', active: true },
  { id: 'd3', name: 'Dr. Vechi Arhivat', active: false }]
const doc = (over: Partial<PiDoctor>): PiDoctor => ({ key: 'k', value: 'v', rows: 1, auto: '', cands: [], choice: '', ...over })
const DOCS: PiDoctor[] = [
  doc({ key: 'popescu', value: 'Popescu', rows: 2 }),
  doc({ key: 'rusu', value: 'Dr. Rusu', cands: ['d1', 'd2'] }),
  doc({ key: 'e rusu', value: 'Rusu E.', rows: 14, auto: 'd1' }),
  doc({ key: 'arhivat', value: 'Arhivat', auto: 'd3' }),
]
const withDocs = (over: Partial<PiCheck> = {}) => checked({ doctors: DOCS, clinic_doctors: CLINIC, ...over })
const docSelect = (value: string) => screen.getByLabelText(`Medic în DentPilot: ${value}`) as HTMLSelectElement
const docRow = (value: string) => docSelect(value).closest('tr') as HTMLElement

async function toDocs(c: PiCheck = withDocs()) {
  await toCols(c)
  fireEvent.click(screen.getByRole('button', { name: /Verifică/ }))
  await waitFor(() => expect(document.querySelector('.pi-docs')).not.toBeNull())
}

describe('ImportScreen: шаг «Medici»', () => {
  it('без колонки врача шага нет: три шага, «Verifică» ведёт сразу к проверке', async () => {
    await open()
    await toCheck()
    expect(Array.from(document.querySelectorAll('.pi-steps li')).map((x) => x.textContent?.replace(/^\d+\s*/, '')))
      .toEqual(['Fișier', 'Coloane', 'Verificare'])
    expect(screen.getByRole('button', { name: /Înapoi la coloane/ })).toBeTruthy()
  })

  it('с колонкой врача — четвёртый шаг: написание, сколько строк, кого узнала программа', async () => {
    await open()
    await toDocs()
    expect(stepNow()).toBe('Medici')
    expect(document.querySelectorAll('.pi-steps li').length).toBe(4)
    expect(['Popescu', 'Dr. Rusu', 'Rusu E.', 'Arhivat'].map((v) => docSelect(v).value)).toEqual(['', '', 'd1', 'd3'])
    expect(docRow('Rusu E.').textContent).toContain('14')
    expect(docRow('Rusu E.').textContent).toContain('recunoscut')
    expect(docRow('Popescu').textContent).toContain('nu recunosc')
    expect(docRow('Dr. Rusu').textContent).toContain('se potrivesc: Dr. Elena Rusu, Dr. Ion Rusu')
    expect(screen.getByRole('status').textContent)
      .toBe('2 scrieri nerecunoscute — rândurile intră fără medic, iar numele din fișier rămâne în notițe.')
  })

  it('в списке — все врачи клиники, выключенный помечен, и «Fără medic»; пустой пункт только у не узнанного', async () => {
    await open()
    await toDocs()
    const labels = (v: string) => Array.from(docSelect(v).options).map((o) => o.textContent)
    expect(labels('Popescu')).toEqual(['— alegeți medicul —', 'Dr. Elena Rusu', 'Dr. Ion Rusu', 'Dr. Vechi Arhivat (inactiv)', 'Fără medic'])
    expect(labels('Rusu E.')).toEqual(['Dr. Elena Rusu', 'Dr. Ion Rusu', 'Dr. Vechi Arhivat (inactiv)', 'Fără medic'])
    expect(docRow('Arhivat').textContent).toContain('medic inactiv în clinică')
  })

  it('выбор — одно решение на написание: уходит в docs и перепроверяет файл, шаг остаётся', async () => {
    await open()
    await toDocs()
    postRaw.mockResolvedValue(ok(withDocs({ opts: { ...checked().opts, docs: { popescu: 'd2' } },
      doctors: [doc({ ...DOCS[0], choice: 'd2' }), ...DOCS.slice(1)] })))
    fireEvent.change(docSelect('Popescu'), { target: { value: 'd2' } })
    await waitFor(() => expect(optsOf(lastRaw()[0]).docs).toEqual({ popescu: 'd2' }))
    await waitFor(() => expect(docSelect('Popescu').value).toBe('d2'))
    expect(docRow('Popescu').textContent).toContain('ales de dvs.')
    expect(stepNow()).toBe('Medici')
    fireEvent.change(docSelect('Dr. Rusu'), { target: { value: '-' } })
    await waitFor(() => expect(optsOf(lastRaw()[0]).docs).toEqual({ popescu: 'd2', rusu: '-' }))
  })

  it('«Continuă» — к проверке без нового запроса; оттуда «Înapoi la medici»; «Înapoi la coloane» — к колонкам', async () => {
    await open()
    await toDocs()
    const calls = postRaw.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: /Continuă/ }))
    await waitFor(() => expect(stepNow()).toBe('Verificare'))
    expect(postRaw.mock.calls.length).toBe(calls)
    fireEvent.click(screen.getByRole('button', { name: /Înapoi la medici/ }))
    await waitFor(() => expect(stepNow()).toBe('Medici'))
    fireEvent.click(screen.getByRole('button', { name: /Înapoi la coloane/ }))
    await waitFor(() => expect(stepNow()).toBe('Coloane'))
  })

  it('импорт уходит с выбором врачей', async () => {
    await open()
    await toDocs(withDocs({ opts: { ...checked().opts, docs: { popescu: '-' } } }))
    fireEvent.click(screen.getByRole('button', { name: /Continuă/ }))
    await waitFor(() => expect(stepNow()).toBe('Verificare'))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    postRaw.mockResolvedValue(runReply(0, true))
    fireEvent.click(screen.getByRole('button', { name: /Importă 400/ }))
    await waitFor(() => expect(lastRaw()[0].startsWith('/pimport/run?')).toBe(true))
    expect(optsOf(lastRaw()[0]).docs).toEqual({ popescu: '-' })
  })
})

describe('ImportScreen: шаг «Verificare»', () => {
  it('счётчики и группы словами сервера, причина и ссылка на совпавшую фишу, остаток группы числом', async () => {
    await open()
    await toCheck()
    expect(stepNow()).toBe('Verificare')
    expect(Array.from(document.querySelectorAll('.pi-count')).map((x) => x.textContent))
      .toEqual(['398 Fișe noi', '2 Cu observații', '2 Există deja', '0 Dubluri în fișier', '1 Nu intră'])
    expect(document.querySelector('.pi-group.dup')).toBeNull()
    expect((document.querySelector('.pi-group.bad') as HTMLDetailsElement).open).toBe(true)
    const exists = document.querySelector('.pi-group.exists') as HTMLElement
    expect(exists.textContent).toContain('există deja (același telefon și nume): Ion Vechi')
    expect(exists.querySelector('a')?.getAttribute('href')).toBe('/admin/patient/41')
    expect(exists.textContent).toContain('se pot completa: adresă, e-mail')
    expect(document.querySelector('.pi-group.new')?.textContent).toContain('și încă 98 de rânduri — lista completă este în raport')
    expect(document.body.textContent).toContain('3 fișe noi au același telefon ca alt pacient')
    expect(screen.getByRole('button', { name: 'Importă 400 de pacienți' })).toBeTruthy()
  })

  it('имя из файла с разметкой печатается текстом', async () => {
    await open()
    await toCheck()
    expect(document.querySelector('.pi-group img')).toBeNull()
    expect(document.querySelector('.pi-group.noted')?.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('«completează câmpurile goale» выключен, подпись честная; включение перепроверяет с fill', async () => {
    await open()
    await toCheck()
    const box = screen.getByLabelText(/Completează câmpurile goale/) as HTMLInputElement
    expect(box.checked).toBe(false)
    expect(document.querySelector('.pi-fill')?.textContent).toContain('Anularea importului nu șterge ce s-a completat aici')
    fireEvent.click(box)
    await waitFor(() => expect(optsOf(lastRaw()[0]).fill).toBe(true))
  })

  it('«posibil dublu»: галочка шлёт номер строки в force', async () => {
    await open()
    await toCheck()
    fireEvent.click(within(document.querySelector('.pi-group.exists') as HTMLElement).getByRole('checkbox'))
    await waitFor(() => expect(optsOf(lastRaw()[0]).force).toEqual([5]))
  })

  it('нечего импортировать — кнопка выключена, сказано словом', async () => {
    await open()
    await toCheck(checked({ counts: { rows: 2, create: 0, new: 0, noted: 0, exists: 2, dup: 0, bad: 0, fill: 0, family: 0 } }))
    expect(screen.getByRole('status').textContent).toMatch(/Nimic nou de importat/)
    expect((document.querySelector('.pi-go') as HTMLButtonElement).disabled).toBe(true)
    expect(document.querySelector('.pi-go')?.textContent?.trim()).toBe('Importă')
  })

  it('новых нет, но есть что дописать: кнопка и вопрос говорят про дополнение, а не про импорт', async () => {
    await open()
    await toCheck(checked({ opts: { ...checked().opts, fill: true },
      counts: { rows: 3400, create: 0, new: 0, noted: 0, exists: 3400, dup: 0, bad: 0, fill: 1200, family: 0 } }))
    expect(document.querySelector('.pi-file')?.textContent).toContain('3 400 de rânduri cu date')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: 'Completează 1 200 de fișe' }))
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0]?.[0]).toBe('Completați câmpurile goale la 1 200 de fișe din „pacienti.xlsx”? Fișe noi nu se creează.')
  })

  it('отчёт до импорта — книга из ответа, без номера импорта', async () => {
    await open()
    await toCheck()
    const blob = new Blob(['x'])
    download.mockResolvedValue(blob)
    fireEvent.click(screen.getByRole('button', { name: /Descarcă raportul/ }))
    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(blob, 'raport-import-pacienti.xlsx'))
    const [path, body] = download.mock.calls[0] as [string, File]
    expect(path.startsWith('/pimport/report?')).toBe(true)
    expect(paramsOf(path).has('import')).toBe(false)
    expect(body).toBe(FILE)
  })
})

describe('ImportScreen: импорт', () => {
  it('без согласия ничего не пишется', async () => {
    await open()
    await toCheck()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: 'Importă 400 de pacienți' }))
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0]?.[0]).toContain('Importați 400 de pacienți din „pacienti.xlsx”?')
    expect(postRaw).toHaveBeenCalledTimes(2)
  })

  it('порции по порядку с отпечатком и номером импорта; итог, отчёт с номером, ссылка на список, фраза про файл', async () => {
    await open()
    await toCheck()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    postRaw.mockReset()
    postRaw.mockResolvedValueOnce(runReply(0, false)).mockResolvedValueOnce(runReply(1, false))
      .mockResolvedValueOnce(runReply(2, true, { ...RUN, created: 400, skipped: 3 }))
    get.mockResolvedValue(ok(home({ imports: [{ ...RUN, created: 400 }] })))
    fireEvent.click(screen.getByRole('button', { name: 'Importă 400 de pacienți' }))
    expect(await screen.findByText('Import finalizat')).toBeTruthy()
    const sent = postRaw.mock.calls.map(([path]) => paramsOf(path as string))
    expect(sent.map((q) => [q.get('part'), q.get('import'), q.get('token')]))
      .toEqual([['0', '0', 'tok32'], ['1', '3', 'tok32'], ['2', '3', 'tok32']])
    expect(document.querySelector('.pi-done-n')?.textContent).toBe('400 de fișe noi · 3 rânduri omise')
    expect(document.querySelector('.pi-done a')?.getAttribute('href')).toBe('/admin/search?imp=3')
    expect(document.body.textContent).toContain('Fișierul sursă rămâne pe calculator')
    await waitFor(() => expect(screen.getByRole('button', { name: /Anulează importul/ })).toBeTruthy())
    download.mockResolvedValue(new Blob(['x']))
    fireEvent.click(screen.getByRole('button', { name: /Descarcă raportul/ }))
    await waitFor(() => expect(download).toHaveBeenCalled())
    expect(paramsOf(download.mock.calls[0]?.[0] as string).get('import')).toBe('3')
  })

  it('полоса называет сделанное: «400 din 403» после второй порции', async () => {
    await open()
    await toCheck()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    postRaw.mockReset()
    let release: (v: unknown) => void = () => {}
    postRaw.mockResolvedValueOnce(runReply(0, false)).mockResolvedValueOnce(runReply(1, false))
      .mockReturnValueOnce(new Promise((r) => { release = r }))
    fireEvent.click(screen.getByRole('button', { name: 'Importă 400 de pacienți' }))
    await waitFor(() => expect(document.querySelector('.pi-run-n')?.textContent).toBe('400 din 403'))
    expect((document.querySelector('.pi-run progress') as HTMLProgressElement).value).toBe(2)
    release(runReply(2, true))
    expect(await screen.findByText('Import finalizat')).toBeTruthy()
  })

  it('обрыв посреди: «Continuă» повторяет ту же порцию тем же импортом', async () => {
    await open()
    await toCheck()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    postRaw.mockReset()
    postRaw.mockResolvedValueOnce(runReply(0, false))
      .mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    fireEvent.click(screen.getByRole('button', { name: 'Importă 400 de pacienți' }))
    expect(await screen.findByText(/Importul s-a întrerupt/)).toBeTruthy()
    postRaw.mockResolvedValueOnce(runReply(1, false)).mockResolvedValueOnce(runReply(2, true))
    fireEvent.click(screen.getByRole('button', { name: /Continuă/ }))
    expect(await screen.findByText('Import finalizat')).toBeTruthy()
    expect(postRaw.mock.calls.map(([path]) => [paramsOf(path as string).get('part'), paramsOf(path as string).get('import')]))
      .toEqual([['0', '0'], ['1', '3'], ['1', '3'], ['2', '3']])
  })

  it('файл или выбор изменились (pi_stale): слова сервера и возврат к проверке', async () => {
    await open()
    await toCheck()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    postRaw.mockReset()
    postRaw.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'pi_stale', text: 'S-a schimbat după verificare' }, 'x'))
      .mockResolvedValue(ok(checked()))
    fireEvent.click(screen.getByRole('button', { name: 'Importă 400 de pacienți' }))
    expect(await screen.findByText('S-a schimbat după verificare')).toBeTruthy()
    await waitFor(() => expect(document.querySelector('.pi-counts')).not.toBeNull())
    expect(lastRaw()[0].startsWith('/pimport/check?')).toBe(true)
  })
})

describe('ImportScreen: прошлые импорты и отмена', () => {
  it('строка импорта: дата, кто, файл, сколько; отменённый — словом и без кнопки', async () => {
    await open(home({ imports: [RUN, { ...RUN, id: 2, file: 'vechi.csv', created: 40, removed: 3, undone: true, can_undo: true }] }))
    const rows = Array.from(document.querySelectorAll('.pi-past tbody tr'))
    expect(rows[0]?.textContent).toContain('12.11.2026 14:44Ana Rpacienti.xlsx180 de fișe noi')
    expect(rows[1]?.textContent).toContain('40 de fișe noi · anulat — au rămas 37 de fișe')
    expect(screen.getAllByRole('button', { name: /Anulează importul/ })).toHaveLength(1)
  })

  it('«Vezi pacienții» в строке импорта ведёт к списку только его фиш; у отменённого — к оставшимся, без остатка ссылки нет', async () => {
    await open(home({ imports: [RUN, { ...RUN, id: 2, created: 40, removed: 3, undone: true },
      { ...RUN, id: 1, created: 5, removed: 5, undone: true, can_undo: false }] }))
    expect(Array.from(document.querySelectorAll('.pi-past tbody tr')).map((tr) => tr.querySelector('a')?.getAttribute('href') ?? null))
      .toEqual(['/admin/search?imp=3', '/admin/search?imp=2', null])
  })

  it('отмена порциями после вопроса; итог честный: сколько осталось и почему', async () => {
    await open(home({ imports: [RUN] }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    post.mockResolvedValueOnce(undoReply({ phase: 'p', after: 0 }))
      .mockResolvedValueOnce(undoReply({ phase: 'p', after: 200, removed: 120 }))
      .mockResolvedValueOnce(undoReply({ done: true, after: 260, removed: 23, kept: 37 }, 'pi_undone', 'Import anulat'))
    get.mockResolvedValue(ok(home({ imports: [{ ...RUN, removed: 143, undone: true }] })))
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    expect(await screen.findByText('S-au șters 143 de fișe. 37 de fișe au rămas — au deja programări sau date medicale.')).toBeTruthy()
    expect(confirm.mock.calls[0]?.[0]).toContain('Anulați importul din „pacienti.xlsx”?')
    expect(post.mock.calls.map(([path]) => path)).toEqual(['/pimport/undo?id=3&phase=v&after=0',
      '/pimport/undo?id=3&phase=p&after=0', '/pimport/undo?id=3&phase=p&after=200'])
    await waitFor(() => expect(document.querySelector('.pi-past')?.textContent).toContain('anulat'))
  })

  it('отмена без остатка — слова сервера; без согласия запроса нет', async () => {
    await open(home({ imports: [RUN] }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(post).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    post.mockResolvedValueOnce(undoReply({ done: true, after: 180, removed: 180 }, 'pi_undone', 'Import anulat'))
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    expect(await screen.findByText('Import anulat')).toBeTruthy()
  })
})

describe('ImportScreen: записи из файла', () => {
  it('без колонки даты записи блока записей нет', async () => {
    await open()
    await toCheck()
    expect(document.querySelector('.pi-visits')).toBeNull()
    expect(screen.getByRole('button', { name: 'Importă 400 de pacienți' })).toBeTruthy()
  })

  it('блок записей: умолчания сервера, счётчики, группа «Nu se programează» открыта со словами причины', async () => {
    await open()
    await toCheck(withVisits())
    const box = document.querySelector('.pi-visits') as HTMLElement
    expect(box.querySelector('h3')?.textContent).toBe('Programări din fișier')
    const past = screen.getByRole('checkbox', { name: /Importă și vizitele trecute/ }) as HTMLInputElement
    expect(past.checked).toBe(true)
    expect(screen.queryByRole('checkbox', { name: /Trimite SMS/ })).toBeNull()
    expect((screen.getByLabelText(/Procedura, când în fișier/) as HTMLSelectElement).value).toBe('consult')
    expect(Array.from(box.querySelectorAll('.pi-count')).map((x) => x.textContent))
      .toEqual(['5 Programări noi', '1 Vizite trecute (istoric)', '2 Nu se programează'])
    const groups = Array.from(document.querySelectorAll<HTMLDetailsElement>('details.pi-group.v_new, details.pi-group.v_past, details.pi-group.v_no'))
    expect(groups.map((g) => [g.classList[2], g.open])).toEqual([['v_new', false], ['v_past', false], ['v_no', true]])
    expect(groups[2]?.textContent).toContain('ocupat — rândul 2 are programare la același medic în acest timp')
    expect(groups[1]?.querySelector('a')?.getAttribute('href')).toBe('/admin/patient/41')
    expect(screen.getByRole('button', { name: 'Importă 400 de pacienți și 6 programări' })).toBeTruthy()
  })

  it('галочки и процедура перепроверяют файл с выбором; SMS — только когда пакет работает, выключена', async () => {
    await open()
    await toCheck(withVisits({ sms_on: true }))
    const sms = screen.getByRole('checkbox', { name: /Trimite SMS de reamintire/ }) as HTMLInputElement
    expect(sms.checked).toBe(false)
    expect(document.body.textContent).toContain('pacienții nu primesc SMS pentru programările din fișier')
    fireEvent.click(screen.getByRole('checkbox', { name: /Importă și vizitele trecute/ }))
    await waitFor(() => expect(optsOf(lastRaw()[0]).past).toBe(false))
    fireEvent.click(sms)
    await waitFor(() => expect(optsOf(lastRaw()[0]).sms).toBe(true))
    fireEvent.change(screen.getByLabelText(/Procedura, când în fișier/), { target: { value: 'hygiene' } })
    await waitFor(() => expect(optsOf(lastRaw()[0]).svc).toBe('hygiene'))
  })

  it('только записи (все пациенты уже есть): кнопка про записи, «nimic» нет', async () => {
    await open()
    await toCheck(withVisits({ counts: { rows: 6, create: 0, new: 0, noted: 0, exists: 6, dup: 0, bad: 0, fill: 0, family: 0 } }))
    expect(screen.getByRole('button', { name: 'Importă 6 programări' }).hasAttribute('disabled')).toBe(false)
    expect(document.querySelector('.banner.warn')).toBeNull()
  })

  it('ни пациентов, ни записей — кнопка выключена, сказано про обе', async () => {
    await open()
    await toCheck(withVisits({ counts: { rows: 2, create: 0, new: 0, noted: 0, exists: 2, dup: 0, bad: 0, fill: 0, family: 0 },
      visits: { ...VISITS, counts: { v_new: 0, v_past: 0, v_no: 2, rows: 2 } } }))
    expect(document.body.textContent).toContain('programările din fișier nu se pot pune')
    expect((screen.getByRole('button', { name: /^Importă/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('вопрос называет записи и что SMS не уйдут; итог — записи, история и «Rechemări» ссылкой', async () => {
    await open()
    await toCheck(withVisits({ sms_on: true }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    postRaw.mockReset()
    const total = { ...RUN, created: 400, skipped: 3, visits: 6, visits_past: 1, visits_skipped: 2 }
    postRaw.mockResolvedValueOnce(runReply(0, false)).mockResolvedValueOnce(runReply(1, false))
      .mockResolvedValueOnce(runReply(2, true, total, { recall: 1 }))
    get.mockResolvedValue(ok(home({ imports: [total] })))
    fireEvent.click(screen.getByRole('button', { name: 'Importă 400 de pacienți și 6 programări' }))
    expect(await screen.findByText('Import finalizat')).toBeTruthy()
    expect(confirm.mock.calls[0]?.[0]).toBe('Importați 400 de pacienți și 6 programări (1 în istoric) din „pacienti.xlsx”? '
      + 'Fișele noi apar imediat în lista de pacienți. Pentru programările din fișier nu se trimit SMS.')
    expect(Array.from(document.querySelectorAll('.pi-done-n')).map((x) => x.textContent)).toEqual([
      '400 de fișe noi · 3 rânduri omise', '6 programări puse (1 în istoric) · 2 nepuse',
      '1 pacient a intrat în „Rechemări” · Deschide Rechemări'])
    expect(screen.getByRole('link', { name: 'Deschide Rechemări' }).getAttribute('href')).toBe('/admin/rechemari')
    expect(document.body.textContent).toContain('coloana „Programare”')
    await waitFor(() => expect(document.querySelector('.pi-past')?.textContent).toContain('6 programări puse'))
  })

  it('шаг «Medici» с датой записи: «Fără medic» значит и без записи', async () => {
    await open()
    const docs = [{ key: 'pop', value: 'Popescu', rows: 2, auto: '', cands: [], choice: '' }]
    await toCols(withVisits({ doctors: docs, clinic_doctors: [{ id: 'd2', name: 'Dr. Activ Doi', active: true }] }))
    fireEvent.click(screen.getByRole('button', { name: /Verifică/ }))
    await waitFor(() => expect(document.querySelector('.pi-docs')).not.toBeNull())
    expect(screen.getByRole('option', { name: 'Fără medic — nu programa' })).toBeTruthy()
    expect(document.querySelector('.pi-docs')?.textContent).toContain('fără programare; numele și data rămân în notițe')
  })

  it('отмена импорта с записями: сперва записи, потом фиши; итог называет и то, и другое', async () => {
    const run = { ...RUN, visits: 6, visits_past: 1 }
    await open(home({ imports: [run] }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    post.mockResolvedValueOnce(undoReply({ phase: 'p', after: 0, visits_removed: 5 }))
      .mockResolvedValueOnce(undoReply({ done: true, after: 190, removed: 179, kept: 1, visits_kept: 1 }, 'pi_undone', 'Import anulat'))
    get.mockResolvedValue(ok(home({ imports: [{ ...run, removed: 179, visits_removed: 5, undone: true }] })))
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    expect(await screen.findByText('S-au șters 179 de fișe. S-au șters 5 programări. 1 fișă a rămas — are deja programări '
      + 'sau date medicale. 1 programare a rămas — s-a lucrat cu ea.')).toBeTruthy()
    expect(confirm.mock.calls[0]?.[0]).toContain('Se șterg programările puse de acest import')
    expect(post.mock.calls.map(([path]) => path)).toEqual(['/pimport/undo?id=3&phase=v&after=0', '/pimport/undo?id=3&phase=p&after=0'])
  })
})

describe('pimport: выбор врача', () => {
  it('выбор кладётся по написанию; пустое значение снимает выбор, прочие не тронуты', () => {
    expect(chooseDoctor({ a: 'd1' }, 'b', '-')).toEqual({ a: 'd1', b: '-' })
    expect(chooseDoctor({ a: 'd1', b: '-' }, 'b', '')).toEqual({ a: 'd1' })
  })
})

describe('pimport: выбор колонок и числа', () => {
  it('одиночное поле — у одной колонки, телефон и заметки — у нескольких', () => {
    expect(assign({ 1: 'full', 2: 'phone' }, 0, 'full')).toEqual({ 0: 'full', 2: 'phone' })
    expect(assign({ 1: 'full', 2: 'phone' }, 3, 'phone')).toEqual({ 1: 'full', 2: 'phone', 3: 'phone' })
    expect(assign({ 1: 'full', 2: 'phone' }, 1, '')).toEqual({ 2: 'phone' })
  })

  it('имя — целиком или частями', () => {
    expect([hasName({ 1: 'full' }), hasName({ 1: 'last' }), hasName({ 1: 'phone', 2: 'notes' })]).toEqual([true, true, false])
  })

  it('разряды — пробелом', () => {
    expect([num(999), num(1200), num(3400000)]).toEqual(['999', '1 200', '3 400 000'])
  })
})

describe('pimport: колонка даты записи', () => {
  it('визиты — по дате или часу записи, не по другим полям', () => {
    expect(hasVisits({ 1: 'full', 2: 'appt' })).toBe(true)
    expect(hasVisits({ 1: 'full', 3: 'appt_time' })).toBe(true)
    expect(hasVisits({ 1: 'full', 2: 'birth', 4: 'appt_note' })).toBe(false)
  })
})
