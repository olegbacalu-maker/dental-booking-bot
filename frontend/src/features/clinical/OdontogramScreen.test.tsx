import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { OdontogramScreen } from './OdontogramScreen'
import { neighbour, surfaceLetter, surfaceName, type Odontogram, type ToothInfo } from './chart'
import { cycleState } from './useChart'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const svgOf = (n: number) =>
  `<svg class='tooth-svg' aria-label='${n}'><path d='M0 0'/><g class='sfz'><circle data-s='M'/><circle data-s='O'/><circle data-s='D'/></g></svg>`

function tooth(n: number, jaw: 'sus' | 'jos', extra: Partial<ToothInfo> = {}): ToothInfo {
  return {
    jaw, mez: 'right', state: 'ok', note: '', doctor: '', at: '', sf: '', sfx: '', sfst: {}, mk: [], mkx: '',
    milk: n > 50, title: `${n} · Sănătos`, bridge: null, svg: { frontal: svgOf(n), occlusal: svgOf(n) }, ...extra,
  }
}

const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const teeth: Record<string, ToothInfo> = {}
for (const n of UPPER) teeth[String(n)] = tooth(n, 'sus')
for (const n of LOWER) teeth[String(n)] = tooth(n, 'jos')
teeth['16'] = tooth(16, 'sus', {
  state: 'carie', sf: 'MO', sfx: 'Carie (M), Obturație (O)', sfst: { M: 'carie', O: 'obturatie' },
  note: 'distal', doctor: 'Dr. Activ Doi', at: '18.09.2026', title: '16 · Carie · distal · Carie (M), Obturație (O)',
})
teeth['47'] = tooth(47, 'jos', { bridge: { role: 'stalp', material: 'zirconiu' }, title: '47 · Sănătos · Punte: Stâlp (zirconiu)' })
teeth['46'] = tooth(46, 'jos', { bridge: { role: 'corp', material: 'zirconiu' } })
teeth['55'] = tooth(55, 'sus')

const MODEL: Odontogram = {
  teeth,
  history: { '16': [{ at: '18.09.2026', text: 'Dinte 16: Carie (MO) · Dr. Activ Doi · distal' }] },
  arches: { upper: UPPER, lower: LOWER, milk_upper: [55], milk_lower: [] },
  arc: { upper: UPPER.map(() => 0), lower: LOWER.map(() => 0), milk_upper: [0], milk_lower: [] },
  milk_open: true,
  bridges: [{ id: 3, teeth: [[47, 'stalp'], [46, 'corp']], material: 'zirconiu', doctor: 'Dr. Activ Doi' }],
  legend: {
    frontal: [{ kind: 'state', key: 'carie', label: 'Carie', svg: '<svg></svg>' }, { kind: 'mark', key: 'tratament', label: 'În tratament', svg: '<svg></svg>' }],
    occlusal: [],
  },
  states: { ok: 'Sănătos', carie: 'Carie', obturatie: 'Obturație', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' },
  marks: { tratament: 'În tratament' },
  surfaces: { M: 'mezial', O: 'ocluzal', D: 'distal', V: 'vestibular', L: 'lingual' },
  surface_states: ['carie', 'obturatie'],
  bridge_roles: { stalp: 'Stâlp', corp: 'Corp de punte' },
  materials: [{ id: 'zirconiu', label: 'Zirconiu' }, { id: 'alt', label: 'Alt material…' }],
  patient: { id: 5, name: 'Odonto Pin', primary_doctor: '' },
  doctors: ['Dr. Activ Doi', 'Dr. Activ Trei'],
  perio: { '16': { at: '18.09.2026', exam: 7, text: 'PD 3 2 3 / 4 2 5 · sângerare 2/6' } },
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const btn = (n: number) => document.querySelector(`.odop .arch .tooth-btn[data-n="${n}"]`) as HTMLButtonElement
const inspector = () => document.querySelector('.insp') as HTMLElement
const root = () => document.querySelector('.odop') as HTMLElement
const key = (k: string, target: Element = root()) => fireEvent.keyDown(target, { key: k })
const hitOf = (n: number, s: string) => btn(n).querySelector(`[data-s='${s}']`) as Element
const picHit = (s: string) => document.querySelector(`.insp-pic [data-s='${s}']`) as Element
const sfState = () => within(inspector()).getByLabelText(/Starea suprafeței/) as HTMLSelectElement
const toothState = () => within(inspector()).getByLabelText('Starea dintelui') as HTMLSelectElement
const sfBtn = (name: string) => within(inspector()).getByRole('button', { name: new RegExp(`^${name}$`) })
const unsaved = () => screen.queryByText('Nesalvat')

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  get.mockResolvedValue(ok(MODEL))
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('surface labels', () => {
  it('ключи данных не меняются, у верхней челюсти L подписан как P', () => {
    expect(surfaceLetter('L', 'sus')).toBe('P')
    expect(surfaceLetter('L', 'jos')).toBe('L')
    expect(surfaceLetter('V', 'sus')).toBe('V')
    expect(surfaceName('L', 'sus', MODEL.surfaces)).toBe('palatinal')
    expect(surfaceName('L', 'jos', MODEL.surfaces)).toBe('lingual')
  })
})

describe('C22: чистые правила', () => {
  it('быстрый цикл идёт по списку сервера и возвращается к «—»', () => {
    const s = ['carie', 'obturatie']
    expect(cycleState('', s)).toBe('carie')
    expect(cycleState('carie', s)).toBe('obturatie')
    expect(cycleState('obturatie', s)).toBe('')
    expect(cycleState('coroana', s)).toBe('carie')   // не из списка — с начала
    expect(cycleState('', [])).toBe('')
  })

  it('сосед по стрелкам: ряд, другая челюсть, край, молочные в своей паре', () => {
    expect(neighbour(MODEL, null, 'ArrowRight')).toBe(18)
    expect(neighbour(MODEL, 16, 'ArrowRight')).toBe(15)
    expect(neighbour(MODEL, 16, 'ArrowLeft')).toBe(17)
    expect(neighbour(MODEL, 18, 'ArrowLeft')).toBeNull()
    expect(neighbour(MODEL, 16, 'ArrowDown')).toBe(46)
    expect(neighbour(MODEL, 46, 'ArrowUp')).toBe(16)
    expect(neighbour(MODEL, 16, 'ArrowUp')).toBeNull()
    expect(neighbour(MODEL, 46, 'ArrowDown')).toBeNull()
    expect(neighbour(MODEL, 55, 'ArrowDown')).toBeNull()
    expect(neighbour(MODEL, 55, 'ArrowRight')).toBeNull()
    expect(neighbour(MODEL, 99, 'ArrowRight')).toBeNull()
  })
})

describe('OdontogramScreen', () => {
  it('дуги из модели: кнопки с серверным SVG и подписью, молочный ряд раскрыт, скобка моста, легенда', async () => {
    render(<OdontogramScreen pid={5} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    expect(document.querySelectorAll('.odop .arch .tooth-btn').length).toBe(33)
    expect(btn(16).getAttribute('title')).toBe('16 · Carie · distal · Carie (M), Obturație (O)')
    expect(btn(16).querySelector("svg[aria-label='16']")).toBeTruthy()
    // номер со стороны корней: у верхней дуги перед рисунком, у нижней после
    expect(btn(16).firstElementChild?.className).toBe('num')
    expect(btn(41).lastElementChild?.className).toBe('num')
    expect((document.querySelector('details.milk') as HTMLDetailsElement).open).toBe(true)
    expect(document.querySelector('.arch.lower.br-room')).toBeTruthy()
    expect(screen.getByText('Carie', { selector: '.lg' })).toBeTruthy()
    expect(screen.getByText('Odonto Pin')).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/patients/5/odontogram', expect.anything())
  })

  it('выбор зуба: из адреса, кликом; инспектор показывает зуб, форму, историю и мост', async () => {
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    expect(btn(16).className).toContain('sel')
    const insp = inspector()
    expect(within(insp).getByText('16', { selector: 'b' })).toBeTruthy()
    expect(within(insp).getByText('Maxilar')).toBeTruthy()
    expect((within(insp).getByLabelText('Starea dintelui') as HTMLSelectElement).value).toBe('carie')
    expect((within(insp).getByLabelText('Notiță (opțional)') as HTMLInputElement).value).toBe('distal')
    expect(within(insp).getByText(/Carie \(MO\)/)).toBeTruthy()
    // поверхности: первая отмеченная выбрана, у верхней челюсти P вместо L
    expect(within(insp).getByRole('button', { name: /^M mezial$/ }).className).toContain('sel')
    expect(within(insp).getByRole('button', { name: /^P palatinal$/ })).toBeTruthy()
    fireEvent.click(btn(47))
    expect(within(inspector()).getByText('47', { selector: 'b' })).toBeTruthy()
    expect(within(inspector()).getByText(/Punte 47-46 \(zirconiu\) - rol: Stâlp/)).toBeTruthy()
    expect(within(inspector()).getByText('Șterge puntea')).toBeTruthy()
  })

  it('клик по поверхности внутри рисунка выбирает зуб и поверхность', async () => {
    render(<OdontogramScreen pid={5} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    fireEvent.click(hitOf(16, 'O'))
    const insp = inspector()
    expect(within(insp).getByText('16', { selector: 'b' })).toBeTruthy()
    expect(within(insp).getByRole('button', { name: /^O ocluzal$/ }).className).toContain('sel')
    expect(sfState().value).toBe('obturatie')
  })

  it('сохранение зуба: намерение явным полем, модель подменяется, плашка сервера', async () => {
    const after: Odontogram = { ...MODEL, teeth: { ...MODEL.teeth, '16': tooth(16, 'sus', { state: 'obturatie', title: '16 · Obturație' }) } }
    post.mockResolvedValueOnce(ok(after, 'ok_card', 'Fișa pacientului a fost actualizată'))
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    const insp = inspector()
    fireEvent.click(within(insp).getByRole('button', { name: /^D distal$/ }))
    fireEvent.change(sfState(), { target: { value: 'carie' } })
    fireEvent.change(toothState(), { target: { value: 'obturatie' } })
    fireEvent.click(within(insp).getByLabelText('În tratament'))
    expect(unsaved()).toBeTruthy()
    fireEvent.click(within(insp).getByText('Salvează'))
    expect(await screen.findByText('Fișa pacientului a fost actualizată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/teeth/16', {
      state: 'obturatie', state0: 'carie', note: 'distal', doctor: 'Dr. Activ Doi',
      surfaces: { M: 'carie', O: 'obturatie', D: 'carie' }, marks: ['tratament'],
    })
    expect(btn(16).getAttribute('title')).toBe('16 · Obturație')
    expect(unsaved()).toBeNull()                       // свежая модель — черновика нет
    expect(btn(16).className).not.toContain('dirty')
  })

  it('мост: режим выбора, роли крайних — опоры, сохранение шлёт пары и материал', async () => {
    post.mockResolvedValueOnce(ok(MODEL, 'ok_punte', 'Puntea a fost salvată'))
    render(<OdontogramScreen pid={5} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /Punte nouă/ }))
    expect(screen.getByText('Continuă').hasAttribute('disabled')).toBe(true)
    fireEvent.click(btn(24))
    fireEvent.click(btn(26))
    fireEvent.click(btn(25))
    fireEvent.click(btn(55))       // молочный — мимо
    expect(btn(24).className).toContain('br-pick')
    expect(btn(55).className).not.toContain('br-pick')
    fireEvent.click(screen.getByText('Continuă'))
    expect(screen.getByText('24 - Stâlp')).toBeTruthy()
    expect(screen.getByText('25 - Corp de punte')).toBeTruthy()
    // диалог открыт — клавиши карты молчат: Esc на карте режим моста не снимает
    key('Escape')
    expect(screen.getByText('Salvează puntea')).toBeTruthy()
    fireEvent.click(screen.getByText('25 - Corp de punte'))
    expect(screen.getByText('25 - Stâlp')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Material'), { target: { value: 'alt' } })
    fireEvent.change(screen.getByLabelText('Materialul punții'), { target: { value: 'aur' } })
    fireEvent.click(screen.getByText('Salvează puntea'))
    expect(await screen.findByText('Puntea a fost salvată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/bridges', {
      teeth: [[24, 'stalp'], [25, 'stalp'], [26, 'stalp']], material: 'alt', material_alt: 'aur', doctor: '',
    })
    expect(screen.queryByText('Continuă')).toBeNull()
  })

  it('снять мост из инспектора', async () => {
    post.mockResolvedValueOnce(ok({ ...MODEL, bridges: [] }, 'ok_punte_del', 'Puntea a fost ștearsă'))
    render(<OdontogramScreen pid={5} t={47} />)
    await waitFor(() => expect(btn(47)).toBeTruthy())
    fireEvent.click(within(inspector()).getByText('Șterge puntea'))
    expect(await screen.findByText('Puntea a fost ștearsă')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/bridges/3/delete', {})
  })

  it('вид: переключение запоминается, как у старой страницы', async () => {
    render(<OdontogramScreen pid={5} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    expect(document.querySelector('#odo')?.getAttribute('data-view')).toBe('frontal')
    fireEvent.click(screen.getByText('Vedere ocluzală'))
    expect(document.querySelector('#odo')?.getAttribute('data-view')).toBe('ocluzal')
    expect(localStorage.getItem('dp_odo_view')).toBe('ocluzal')
    expect(document.querySelector('.odo-view.v-ocluzal .arch.occ')).toBeTruthy()
  })

  it('отказ сервера — текст сервера, ввод остаётся; 404 и 401', async () => {
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_card', text: 'Date invalide', field: 'state' }, 'v'))
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    fireEvent.change(within(inspector()).getByLabelText('Notiță (opțional)'), { target: { value: 'nou' } })
    fireEvent.click(within(inspector()).getByText('Salvează'))
    expect(await screen.findByText('Date invalide')).toBeTruthy()
    expect((within(inspector()).getByLabelText('Notiță (opțional)') as HTMLInputElement).value).toBe('nou')
    expect(unsaved()).toBeTruthy()
    cleanup()
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 's'))
    render(<OdontogramScreen pid={5} />)
    expect(await screen.findByText('Fișa nu există sau a fost ștearsă.')).toBeTruthy()
    cleanup()
    get.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    render(<OdontogramScreen pid={5} navigate={navigate} />)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})

describe('C22: поверхность как первичный жест, черновик, клавиатура, меню', () => {
  it('быстрый цикл: повторный клик по выбранной поверхности крутит её состояние, черновик явный', async () => {
    render(<OdontogramScreen pid={5} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    fireEvent.click(hitOf(16, 'O'))                        // выбор зуба и поверхности — без правки
    expect(sfState().value).toBe('obturatie')
    expect(unsaved()).toBeNull()
    fireEvent.click(hitOf(16, 'O'))                        // obturatie → «—»
    expect(sfState().value).toBe('')
    expect(unsaved()).toBeTruthy()
    expect(btn(16).className).toContain('dirty')
    fireEvent.click(hitOf(16, 'O'))                        // «—» → carie
    expect(sfState().value).toBe('carie')
    expect(sfBtn('O ocluzal').className).toContain('sf-carie')
    fireEvent.click(hitOf(16, 'O'))                        // carie → obturatie: как в модели, черновика больше нет
    expect(sfState().value).toBe('obturatie')
    expect(unsaved()).toBeNull()
    expect(btn(16).className).not.toContain('dirty')
    // рисунок в инспекторе — тот же путь: первый клик выбирает M, второй крутит
    fireEvent.click(picHit('M'))
    expect(sfBtn('M mezial').className).toContain('sel')
    expect(sfState().value).toBe('carie')
    fireEvent.click(picHit('M'))
    expect(sfState().value).toBe('obturatie')
    expect(unsaved()).toBeTruthy()
    fireEvent.click(screen.getByText('Renunță'))
    expect(sfState().value).toBe('carie')
    expect(unsaved()).toBeNull()
    expect(post).not.toHaveBeenCalled()                    // цикл ничего не пишет сам
  })

  it('клавиатура: стрелки — сосед по ряду и та же позиция другой челюсти, буквы — поверхность, P только сверху', async () => {
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    expect(document.activeElement).toBe(btn(16))           // зуб из адреса — в фокусе, клавиши работают сразу
    key('ArrowRight')
    expect(btn(15).className).toContain('sel')
    expect(document.activeElement).toBe(btn(15))
    key('ArrowDown')
    expect(btn(45).className).toContain('sel')
    key('ArrowUp')
    expect(btn(15).className).toContain('sel')
    key('ArrowLeft'); key('ArrowLeft'); key('ArrowLeft')
    expect(btn(18).className).toContain('sel')
    key('ArrowLeft')
    expect(btn(18).className).toContain('sel')             // край ряда
    key('ArrowUp')
    expect(btn(18).className).toContain('sel')             // выше верхней челюсти нет
    key('d')
    expect(sfBtn('D distal').className).toContain('sel')
    key('p')
    expect(sfBtn('P palatinal').className).toContain('sel') // алиас L на верхней челюсти
    key('ArrowDown')
    expect(btn(48).className).toContain('sel')
    key('p')
    expect(sfBtn('L lingual').className).not.toContain('sel') // внизу P ничего не значит
    expect(sfBtn('O ocluzal').className).toContain('sel')
    key('v')
    expect(sfBtn('V vestibular').className).toContain('sel')
    key('x')                                               // чужая буква — ничего
    expect(sfBtn('V vestibular').className).toContain('sel')
  })

  it('Enter записывает черновик, когда карта в фокусе; в поле ввода — нет; Esc сбрасывает', async () => {
    const after: Odontogram = {
      ...MODEL,
      teeth: { ...MODEL.teeth, '16': tooth(16, 'sus', { state: 'carie', sf: 'M', sfx: 'Carie (M)', sfst: { M: 'carie' }, note: 'distal', doctor: 'Dr. Activ Doi', title: '16 · Carie · distal · Carie (M)' }) },
    }
    post.mockResolvedValue(ok(after, 'ok_card', 'Fișa pacientului a fost actualizată'))
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    key('Enter')
    expect(post).not.toHaveBeenCalled()                    // нечего записывать
    fireEvent.click(hitOf(16, 'O'))
    fireEvent.click(hitOf(16, 'O'))                        // O: obturatie → «—»
    expect(unsaved()).toBeTruthy()
    fireEvent.keyDown(within(inspector()).getByLabelText('Notiță (opțional)'), { key: 'Enter' })
    expect(post).not.toHaveBeenCalled()                    // в поле ввода Enter — браузерный
    fireEvent.keyDown(toothState(), { key: 'Escape' })
    expect(unsaved()).toBeTruthy()                         // и Esc в списке черновик не трогает
    key('Escape')
    expect(unsaved()).toBeNull()
    expect(sfState().value).toBe('obturatie')
    fireEvent.click(hitOf(16, 'O'))                        // поверхность O всё ещё выбрана — сразу цикл
    expect(unsaved()).toBeTruthy()
    fireEvent.keyDown(btn(16), { key: 'Enter' })           // фокус на зубе внутри карты
    expect(post).toHaveBeenCalledWith('/patients/5/teeth/16', {
      state: 'carie', state0: 'carie', note: 'distal', doctor: 'Dr. Activ Doi', surfaces: { M: 'carie' }, marks: [],
    })
    expect(await screen.findByText('Fișa pacientului a fost actualizată')).toBeTruthy()
    expect(unsaved()).toBeNull()
    expect(btn(16).className).not.toContain('dirty')
    expect(btn(16).getAttribute('title')).toBe('16 · Carie · distal · Carie (M)')
  })

  it('черновик держится за зубом: клик по соседу правку не теряет, на дуге зуб помечен', async () => {
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    fireEvent.change(toothState(), { target: { value: 'coroana' } })
    expect(btn(16).className).toContain('dirty')
    fireEvent.click(btn(21))
    expect(unsaved()).toBeNull()                           // у 21 правки нет
    expect(btn(16).className).toContain('dirty')           // а у 16 есть — видно на дуге
    expect(btn(16).className).not.toContain('sel')
    fireEvent.click(btn(16))
    expect(toothState().value).toBe('coroana')
    expect(unsaved()).toBeTruthy()
  })

  it('контекстное меню: состояние — в черновик, мост от зуба; у молочного моста нет; в режиме моста меню нет', async () => {
    render(<OdontogramScreen pid={5} t={16} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    fireEvent.contextMenu(btn(21), { clientX: 300, clientY: 200 })
    const menu = screen.getByRole('menu')
    expect(within(menu).getByText('Dinte 21')).toBeTruthy()
    expect(within(menu).getByRole('menuitemradio', { name: 'Sănătos' }).getAttribute('aria-checked')).toBe('true')
    fireEvent.click(within(menu).getByText('Coroană'))
    expect(screen.queryByRole('menu')).toBeNull()
    expect(btn(21).className).toContain('sel')
    expect(btn(21).className).toContain('dirty')
    expect(toothState().value).toBe('coroana')
    expect(unsaved()).toBeTruthy()
    expect(post).not.toHaveBeenCalled()                    // меню не пишет само
    fireEvent.contextMenu(btn(21))
    expect(within(screen.getByRole('menu')).getByRole('menuitemradio', { name: 'Coroană' }).getAttribute('aria-checked')).toBe('true')
    key('Escape')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(unsaved()).toBeTruthy()                         // Esc закрыл меню, черновик не тронул
    fireEvent.contextMenu(btn(55))
    expect(within(screen.getByRole('menu')).queryByText('Punte nouă de la acest dinte')).toBeNull()
    fireEvent.contextMenu(btn(24))
    fireEvent.click(within(screen.getByRole('menu')).getByText('Punte nouă de la acest dinte'))
    expect(btn(24).className).toContain('br-pick')
    expect(screen.getByText('Continuă')).toBeTruthy()
    fireEvent.contextMenu(btn(25))
    expect(screen.queryByRole('menu')).toBeNull()          // в режиме моста меню не открывается
    key('ArrowRight')
    expect(btn(25).className).not.toContain('sel')         // и стрелки молчат
    key('Escape')
    expect(screen.queryByText('Continuă')).toBeNull()      // Esc выходит из режима моста
    // тот же путь из инспектора — меню не единственный
    fireEvent.click(btn(16))
    fireEvent.click(within(inspector()).getByText('Punte nouă de la acest dinte'))
    expect(btn(16).className).toContain('br-pick')
    expect(screen.getByText('Continuă')).toBeTruthy()
  })
})

describe('замер пародонта в инспекторе', () => {
  it('у зуба с осмотром — строка сервера и ссылка в тот же осмотр', async () => {
    render(<OdontogramScreen pid={5} t={16} navigate={() => {}} />)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    const box = document.querySelector('.i-perio') as HTMLElement
    expect(box.textContent).toContain('PD 3 2 3 / 4 2 5 · sângerare 2/6')
    expect(box.textContent).toContain('18.09.2026')
    expect(box.querySelector('a')?.getAttribute('href'))
      .toBe('/admin/patient/5/parodontograma?exam=7')
  })

  it('у зуба без осмотра блока нет — нулей не выдумываем', async () => {
    render(<OdontogramScreen pid={5} t={21} navigate={() => {}} />)
    await waitFor(() => expect(btn(21)).toBeTruthy())
    expect(document.querySelector('.i-perio')).toBeNull()
  })
})
