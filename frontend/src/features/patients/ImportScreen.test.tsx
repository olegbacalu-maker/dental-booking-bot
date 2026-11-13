import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { openScreen } from '../../test/openScreen'
import { ImportScreen, loadPimport } from './ImportScreen'
import { assign, hasName, num, type PiCheck, type PiGroup, type PiHome, type PiImport, type PiRow } from './pimport'

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
  created: 180, filled: 0, skipped: 20, removed: 0, undone: false, can_undo: true }

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
    opts: { sheet: 0, header: 1, cols: { 1: 'full', 2: 'birth', 3: 'phone' }, enc: '', delim: '', fill: false, force: [] },
    columns: [{ index: 0, letter: 'A', title: 'ID', field: '' }, { index: 1, letter: 'B', title: 'Nume și prenume', field: 'full' },
      { index: 2, letter: 'C', title: 'Data nașterii', field: 'birth' }, { index: 3, letter: 'D', title: 'Telefon', field: 'phone' }],
    preview: [{ line: 2, cells: ['1', 'Ana Test', '01.01.1950', '069111222'] },
      { line: 3, cells: ['2', '<b>Ion</b>', '', ''] }],
    ready: true,
    counts: { rows: 403, create: 400, new: 398, noted: 2, exists: 2, dup: 0, bad: 1, fill: 1, family: 3 },
    groups: GROUPS, token: 'tok32', parts: 3,
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
const runReply = (part: number, done: boolean, total: PiImport = RUN) => ok(
  { import: 3, part, parts: 3, done, created: 200, filled: 0, skipped: 0, total }, done ? 'pi_done' : '', done ? 'Import finalizat' : '')

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
    post.mockResolvedValueOnce(ok({ done: false, after: 200, removed: 120, kept: 0, total: RUN }))
      .mockResolvedValueOnce(ok({ done: true, after: 260, removed: 23, kept: 37, total: RUN }, 'pi_undone', 'Import anulat'))
    get.mockResolvedValue(ok(home({ imports: [{ ...RUN, removed: 143, undone: true }] })))
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    expect(await screen.findByText('S-au șters 143 de fișe. 37 de fișe au rămas — au deja programări sau date medicale.')).toBeTruthy()
    expect(confirm.mock.calls[0]?.[0]).toContain('Anulați importul din „pacienti.xlsx”?')
    expect(post.mock.calls.map(([path]) => path)).toEqual(['/pimport/undo?id=3&after=0', '/pimport/undo?id=3&after=200'])
    await waitFor(() => expect(document.querySelector('.pi-past')?.textContent).toContain('anulat'))
  })

  it('отмена без остатка — слова сервера; без согласия запроса нет', async () => {
    await open(home({ imports: [RUN] }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(post).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    post.mockResolvedValueOnce(ok({ done: true, after: 180, removed: 180, kept: 0, total: RUN }, 'pi_undone', 'Import anulat'))
    fireEvent.click(screen.getByRole('button', { name: /Anulează importul/ }))
    expect(await screen.findByText('Import anulat')).toBeTruthy()
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
