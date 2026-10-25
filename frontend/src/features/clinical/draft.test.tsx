import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import { ApiError } from '../../types/api'
import type { Odontogram, TeethItem, ToothInfo } from './chart'
import { loadOdontogram, OdontogramScreen } from './OdontogramScreen'

/* Волна 2 одонтограммы (Олег 25.10: «сначала всю работу и потом сохранить, а
   если не сохранил и хочет выйти — напомнить»): запись всех зубов разом,
   черновик в видах до записи (предпросмотр сервера), сцена не играет дважды,
   поздний предпросмотр мимо, черновики переживают мост и план, конфликт,
   вопрос при уходе (адрес, F5 в оболочке, beforeunload без неё), печать,
   фокус без прокрутки. Остальное рабочего стола — OdontogramScreen.test. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

/* Сцена 3D в jsdom не рисуется — вместо неё запись того, что ей отдали: зуб 16
   на каждом кадре. По нему видно, когда сцена сыграла бы смену состояния
   (`scene.paint` играет её только при смене вида зуба). */
const { frames } = vi.hoisted(() => ({ frames: [] as string[] }))
vi.mock('./three/Odontogram3D', () => ({
  Odontogram3D: ({ model }: { model: Odontogram }) => {
    frames.push(model.teeth['16']!.state)
    return <div className="odo-stage" data-t16={model.teeth['16']!.state} />
  },
}))

/* Мост к оболочке: что заявил экран (`useCommand`) и стоит ли окно оболочки. */
const { claims, shell } = vi.hoisted(() => ({ claims: new Map<string, () => void>(), shell: { on: false } }))
vi.mock('../../app/bridge', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../app/bridge')>(),
  shellOn: () => shell.on,
  useCommand: (id: string, run: (() => void) | null | false | undefined) => {
    if (run) claims.set(id, run)
    else claims.delete(id)
  },
}))
const { reload } = vi.hoisted(() => ({ reload: vi.fn() }))
vi.mock('../../hooks/useLive', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../hooks/useLive')>(),
  defaultReload: reload,
}))

const svgOf = (n: number, mark = 'saved') =>
  `<svg class='tooth-svg' aria-label='${n}' data-pic='${mark}'><path d='M0 0'/><g class='sfz'><circle data-s='O'/></g></svg>`

function tooth(n: number, jaw: 'sus' | 'jos', extra: Partial<ToothInfo> = {}): ToothInfo {
  return {
    jaw, mez: 'right', state: 'ok', note: '', doctor: '', at: '', sf: '', sfx: '', sfst: {}, mk: [], mkx: '',
    milk: false, title: `${n} · Sănătos`, bridge: null, svg: { frontal: svgOf(n), occlusal: svgOf(n) }, ...extra,
  }
}

const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const teeth: Record<string, ToothInfo> = {}
for (const n of UPPER) teeth[String(n)] = tooth(n, 'sus')
for (const n of LOWER) teeth[String(n)] = tooth(n, 'jos')
teeth['16'] = tooth(16, 'sus', { state: 'carie', sf: 'M', sfst: { M: 'carie' }, doctor: 'Dr. Activ Doi', title: '16 · Carie' })

const MODEL: Odontogram = {
  teeth,
  history: {},
  arches: { upper: UPPER, lower: LOWER, milk_upper: [], milk_lower: [] },
  arc: { upper: UPPER.map(() => 0), lower: LOWER.map(() => 0), milk_upper: [], milk_lower: [] },
  milk_open: false,
  bridges: [],
  legend: { frontal: [], occlusal: [] },
  states: { ok: 'Sănătos', carie: 'Carie', obturatie: 'Obturație', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' },
  marks: { tratament: 'În tratament', devital: 'Nerv extras' },
  surfaces: { M: 'mezial', O: 'ocluzal', D: 'distal', V: 'vestibular', L: 'lingual' },
  surface_states: ['carie', 'obturatie'],
  tooth_states: { ok: 'Sănătos', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' },
  bridge_roles: { stalp: 'Stâlp', corp: 'Corp de punte' },
  materials: [{ id: 'zirconiu', label: 'Zirconiu' }],
  patient: { id: 5, name: 'Odonto Ciornă', primary_doctor: '' },
  doctors: ['Dr. Activ Doi'],
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const SAVED = 'Fișa pacientului a fost actualizată'

/* «Сервер»: предпросмотр рисует зуб черновика (рисунок с меткой состояния),
   запись кладёт в модель РОВНО то же — правило сервера (предпросмотр =
   записанное) держит test_odontogram_api.suite_batch. */
const drawn = (d: TeethItem): ToothInfo => ({
  ...MODEL.teeth[String(d.n)]!, state: d.state, sfst: d.surfaces, mk: d.marks, note: d.note, doctor: d.doctor,
  title: `${d.n} · ${MODEL.states[d.state]}`, svg: { frontal: svgOf(d.n, `draft-${d.state}`), occlusal: svgOf(d.n, `draft-${d.state}`) },
})
const previewOf = (body: { teeth: TeethItem[] }) => ok({ teeth: Object.fromEntries(body.teeth.map((d) => [String(d.n), drawn(d)])) })
let model = MODEL
const written = (body: { teeth: TeethItem[] }): Odontogram =>
  (model = { ...model, teeth: { ...model.teeth, ...Object.fromEntries(body.teeth.map((d) => [String(d.n), drawn(d)])) } })
const isPreview = (url: unknown) => String(url).endsWith('/odontogram/preview')
const saves = () => post.mock.calls.filter((c) => !isPreview(c[0]))
/* предпросмотр по вызову: `hold` — придержать ответ, пока проверка его не отпустит */
let hold: Promise<void> | null = null
function serve(other: (url: string, body: unknown) => Promise<unknown> = () => Promise.reject(new Error('нет подмены'))) {
  post.mockImplementation(async (url: string, body: { teeth: TeethItem[] }) => {
    if (isPreview(url)) {
      if (hold) await hold
      return previewOf(body)
    }
    if (url.startsWith('/patients/5/teeth')) return ok(written(body), 'ok_card', SAVED)
    return other(url, body)
  })
}

const btn = (n: number) => document.querySelector(`.odop .arch .tooth-btn[data-n="${n}"]`) as HTMLButtonElement
const pic = (n: number) => btn(n).querySelector('[data-pic]')?.getAttribute('data-pic')
const inspector = () => document.querySelector('.insp') as HTMLElement
const root = () => document.querySelector('.odop') as HTMLElement
const saveBtn = () => within(inspector()).getByRole('button', { name: /^Salvează/ }) as HTMLButtonElement
const tabTo = (name: string) => {
  const t = within(inspector()).getByRole('tab', { name: new RegExp(`^${name}`) })
  if (t.getAttribute('aria-selected') !== 'true') fireEvent.click(t)
}
const setState = (n: number, label: string) => {
  fireEvent.contextMenu(btn(n), { clientX: 300, clientY: 200 })
  fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitemradio', { name: label }))
}
const note = (n: number, text: string) => {
  fireEvent.click(btn(n))
  tabTo('Notițe')
  fireEvent.change(within(inspector()).getByLabelText('Notiță (opțional)'), { target: { value: text } })
}
const open = (t?: number) => openScreen(
  '/admin/patient/:pid/odontograma', `/admin/patient/5/odontograma${t !== undefined ? `?t=${t}` : ''}`,
  <OdontogramScreen pid={5} />, loadOdontogram)
const ready = () => waitFor(() => expect(btn(16)).toBeTruthy())

beforeEach(() => {
  model = MODEL
  hold = null
  frames.length = 0
  claims.clear()
  shell.on = false
  get.mockImplementation(() => Promise.resolve(ok(model)))
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  reload.mockReset()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('волна 2: запись всех зубов разом', () => {
  it('три зуба — одна запись «Salvează tot (3)», зубы по возрастанию с base; ответ снимает черновики; Enter — то же', async () => {
    serve()
    open()
    await ready()
    setState(36, 'Implant')
    note(21, 'verificat')
    setState(16, 'Coroană')
    expect(saveBtn().textContent).toContain('Salvează tot (3)')
    expect(within(inspector()).getByText('și dinții 21, 36')).toBeTruthy()
    fireEvent.click(saveBtn())
    expect(await screen.findByText(SAVED)).toBeTruthy()
    expect(saves()).toEqual([['/patients/5/teeth', { teeth: [
      expect.objectContaining({ n: 16, state: 'coroana', state0: 'carie',
        base: { state: 'carie', sfst: { M: 'carie' }, marks: [], doctor: 'Dr. Activ Doi', note: '' } }),
      expect.objectContaining({ n: 21, state: 'ok', note: 'verificat', base: expect.objectContaining({ note: '' }) }),
      expect.objectContaining({ n: 36, state: 'implant', state0: 'ok' }),
    ] }]])
    expect(post.mock.calls.some((c) => /\/teeth\/\d+/.test(String(c[0])))).toBe(false)   // поштучной записи нет
    await waitFor(() => expect(document.querySelectorAll('.odop .dirty').length).toBe(0))
    expect(within(inspector()).getByText('Salvat: dinții 16, 21, 36')).toBeTruthy()
    expect(saveBtn().disabled).toBe(true)
    /* Enter — та же запись всех */
    setState(24, 'Coroană')
    note(25, 'x')
    fireEvent.keyDown(btn(25), { key: 'Enter' })
    await waitFor(() => expect(saves().length).toBe(2))
    expect((saves()[1]![1] as { teeth: TeethItem[] }).teeth.map((t) => t.n)).toEqual([24, 25])
  })
})

describe('волна 2: черновик виден до записи', () => {
  it('дуга (2D) рисует предпросмотр сервера сразу; Esc возвращает сохранённое; кольцо «нет записи» — до записи', async () => {
    serve()
    open()
    await ready()
    setState(16, 'Implant')
    await waitFor(() => expect(pic(16)).toBe('draft-implant'))
    expect(btn(16).className).toContain('dirty')
    expect(saves()).toEqual([])                                      // предпросмотр — не запись
    fireEvent.keyDown(root(), { key: 'Escape' })
    expect(pic(16)).toBe('saved')
    expect(btn(16).className).not.toContain('dirty')
  })

  it('3D: сцена получает черновик в момент выбора и после записи — тот же зуб, без кадра со старым (второй раз не играет)', async () => {
    localStorage.setItem('dp_odo_view', '3d')
    serve()
    open(16)
    await waitFor(() => expect(document.querySelector('.odo-stage')).toBeTruthy())
    tabTo('Diagnostic')
    fireEvent.click(within(within(inspector()).getByRole('group', { name: 'Starea dintelui' })).getByRole('button', { name: 'Implant' }))
    await waitFor(() => expect(frames.at(-1)).toBe('implant'))
    fireEvent.click(saveBtn())
    expect(await screen.findByText(SAVED)).toBeTruthy()
    const seq = frames.filter((s, i) => i === 0 || s !== frames[i - 1])
    expect(seq).toEqual(['carie', 'implant'])
    /* Esc после записи — черновика нет, сцена на записанном */
    fireEvent.keyDown(root(), { key: 'Escape' })
    expect(frames.at(-1)).toBe('implant')
  })

  it('поздний предпросмотр отменённого и уже записанного зуба — мимо', async () => {
    let release: () => void = () => {}
    hold = new Promise<void>((r) => { release = r })
    serve()
    open()
    await ready()
    setState(16, 'Implant')
    await waitFor(() => expect(post.mock.calls.some((c) => isPreview(c[0]))).toBe(true))
    fireEvent.keyDown(root(), { key: 'Escape' })                    // отменён, пока ответ в пути
    await act(async () => { release() })
    expect(pic(16)).toBe('saved')
    setState(16, 'Coroană')                                          // новый черновик того же зуба
    expect(pic(16)).toBe('saved')                                    // implant старого ответа к нему не прилип
    await waitFor(() => expect(pic(16)).toBe('draft-coroana'))
    /* записан, пока предпросмотр в пути: ответ после записи — мимо */
    hold = new Promise<void>((r) => { release = r })
    setState(24, 'Implant')
    fireEvent.click(saveBtn())
    expect(await screen.findByText(SAVED)).toBeTruthy()
    model = { ...model, teeth: { ...model.teeth, '24': { ...model.teeth['24']!, svg: { frontal: svgOf(24, 'written'), occlusal: svgOf(24, 'written') } } } }
    await act(async () => { release() })
    expect(btn(24).className).not.toContain('dirty')
  })
})

describe('волна 2: черновики переживают мост и план', () => {
  it('«Punte nouă» и «Adaugă în plan» подменяют модель — черновики зубов на месте, запись потом пишет их все', async () => {
    serve((url) => {
      if (url === '/patients/5/bridges') {
        return Promise.resolve(ok(model = { ...model, bridges: [{ id: 9, teeth: [[24, 'stalp'], [25, 'corp'], [26, 'stalp']], material: 'zirconiu', doctor: '' }] }, 'ok_punte', 'Puntea a fost salvată'))
      }
      if (url.startsWith('/patients/5/plan?odo=1')) return Promise.resolve(ok(model, 'ok_card', 'Poziția a fost adăugată'))
      return Promise.reject(new Error(url))
    })
    open()
    await ready()
    setState(16, 'Implant')
    note(21, 'ciornă')
    fireEvent.click(screen.getByRole('button', { name: /Punte nouă/ }))
    fireEvent.click(btn(24))
    fireEvent.click(btn(26))
    fireEvent.click(screen.getByText('Continuă'))
    fireEvent.click(screen.getByText('Salvează puntea'))
    expect(await screen.findByText('Puntea a fost salvată')).toBeTruthy()
    expect(btn(16).className).toContain('dirty')
    expect(btn(21).className).toContain('dirty')
    fireEvent.contextMenu(btn(36), { clientX: 300, clientY: 200 })
    fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Adaugă în plan' }))
    const dlg = document.querySelector('dialog.dp-plan-dlg') as HTMLDialogElement
    fireEvent.change(within(dlg).getByLabelText('Procedură (ex. Coroană zirconiu)'), { target: { value: 'Implant 36' } })
    fireEvent.click(within(dlg).getByRole('button', { name: 'Adaugă în plan' }))
    expect(await screen.findByText('Poziția a fost adăugată')).toBeTruthy()
    expect(btn(16).className).toContain('dirty')
    expect(btn(21).className).toContain('dirty')
    expect(pic(16)).toBe('draft-implant')
    fireEvent.click(btn(16))
    fireEvent.click(saveBtn())
    await waitFor(() => expect(saves().filter((c) => String(c[0]).startsWith('/patients/5/teeth')).length).toBe(1))
    const sent = saves().find((c) => String(c[0]).startsWith('/patients/5/teeth'))![1] as { teeth: TeethItem[] }
    expect(sent.teeth.map((t) => t.n)).toEqual([16, 21])
  })
})

describe('волна 2: конфликт', () => {
  it('409: плашка сервера с номером, модель перечитана, черновик конфликтного зуба ушёл, прочие живы', async () => {
    serve()
    post.mockImplementation(async (url: string, body: { teeth: TeethItem[] }) => {
      if (isPreview(url)) return previewOf(body)
      throw new ApiError({ kind: 'conflict', code: 'odo_conflict',
        text: 'Dintele 21 a fost modificat între timp pe alt calculator. Nimic nu a fost salvat — verificați dintele și salvați din nou.' }, 'c')
    })
    open()
    await ready()
    setState(16, 'Implant')
    note(21, 'a mea')
    /* «другой компьютер» записал 21, пока экран его правил */
    model = { ...model, teeth: { ...model.teeth, '21': tooth(21, 'sus', { state: 'coroana', title: '21 · Coroană' }) } }
    const loads = get.mock.calls.length
    fireEvent.click(saveBtn())
    expect(await screen.findByText(/Dintele 21 a fost modificat între timp/)).toBeTruthy()
    await waitFor(() => expect(get.mock.calls.length).toBe(loads + 1))
    await waitFor(() => expect(btn(21).className).not.toContain('dirty'))
    expect(btn(21).getAttribute('title')).toBe('21 · Coroană')
    expect(btn(16).className).toContain('dirty')
    expect(saveBtn().textContent).toContain('Salvează')
    expect(saveBtn().textContent).not.toContain('tot')
  })
})

describe('волна 2: вопрос при уходе', () => {
  it('уход адресом с детальной страницы — вопрос с зубами; отказ — на месте, черновик цел', async () => {
    serve()
    const { router } = open()
    await ready()
    setState(16, 'Implant')
    note(21, 'x')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    fireEvent.click(screen.getByRole('link', { name: /Odonto Ciornă/ }))
    await waitFor(() => expect(confirm).toHaveBeenLastCalledWith(
      'Dinții 16, 21 au modificări nesalvate în formula dentară. Părăsiți formula dentară fără să le salvați?'))
    expect(router.state.location.pathname).toBe('/admin/patient/5/odontograma')
    expect(btn(16).className).toContain('dirty')
    /* смена `?t=` — не уход */
    confirm.mockClear()
    await act(() => router.navigate('/admin/patient/5/odontograma?t=21'))
    expect(confirm).not.toHaveBeenCalled()
  })

  it('без оболочки — beforeunload только с черновиком; в окне оболочки не ставится, F5 («Reîncarcă») спрашивает своим окном', async () => {
    serve()
    open()
    await ready()
    const unload = () => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented }
    expect(unload()).toBe(false)
    expect(claims.has('act:reload')).toBe(false)
    setState(16, 'Implant')
    expect(unload()).toBe(true)
    fireEvent.keyDown(root(), { key: 'Escape' })
    expect(unload()).toBe(false)
    cleanup()
    /* окно оболочки: F5 — команда страницы, `beforeunload` её переходы будил бы */
    shell.on = true
    open()
    await ready()
    setState(16, 'Implant')
    expect(unload()).toBe(false)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    act(() => claims.get('act:reload')!())
    await waitFor(() => expect(confirm).toHaveBeenLastCalledWith(
      'Dintele 16 are modificări nesalvate în formula dentară. Reîncărcați pagina fără să le salvați?'))
    expect(reload).not.toHaveBeenCalled()
    confirm.mockReturnValueOnce(true)
    act(() => claims.get('act:reload')!())
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
  })
})

describe('волна 2: печать', () => {
  it('черновики на экране — сперва вопрос: отказ — ни записи, ни печати; «Salvează și tipărește» — запись, потом печать', async () => {
    serve()
    const print = vi.fn()
    window.print = print
    open()
    await ready()
    const printBtn = () => screen.getByRole('button', { name: 'Printează' })
    fireEvent.click(printBtn())
    await waitFor(() => expect(print).toHaveBeenCalledTimes(1))       // без черновиков — сразу
    setState(16, 'Implant')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    fireEvent.click(printBtn())
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(
      'Dintele 16 are modificări nesalvate în formula dentară. Pe foaie ajunge doar ce e salvat. Salvați acum și tipăriți?'))
    expect(saves()).toEqual([])
    expect(print).toHaveBeenCalledTimes(1)
    confirm.mockReturnValueOnce(true)
    fireEvent.click(printBtn())
    await waitFor(() => expect(print).toHaveBeenCalledTimes(2))
    expect(saves().length).toBe(1)
    expect(btn(16).className).not.toContain('dirty')                // печатается записанное
    /* «Tipărește…» меню окна — то же действие */
    setState(24, 'Coroană')
    confirm.mockReturnValueOnce(false)
    act(() => claims.get('act:print')!())
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(3))
    expect(print).toHaveBeenCalledTimes(2)
  })
})

describe('прыжок экрана (Олег 25.10: «экран прыгает на зуб»)', () => {
  it('меню зуба: фокус на кнопку зуба — без прокрутки страницы', async () => {
    serve()
    open()
    await ready()
    const focus = vi.spyOn(HTMLElement.prototype, 'focus')
    setState(16, 'Implant')
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    expect(focus.mock.calls.every((c) => (c[0] as FocusOptions | undefined)?.preventScroll === true)).toBe(true)
  })
})
