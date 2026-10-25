import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import type { Compare, Odontogram, ToothInfo } from './chart'
import { loadOdontogram, OdontogramScreen } from './OdontogramScreen'

/* «Compară» (волна 2 одонтограммы, 25.10): выбор визита, отметки изменившихся
   зубов (гашение прочих), «было» в 2D и 3D тем же `shown`-путём, что черновик,
   визит без истории — «нет данных», правка выключена, пока сравнение открыто,
   и слой не попадает в печать. Разницу считает сервер — test_odontogram_api.
   suite_compare. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

/* Сцена 3D в jsdom не рисуется — вместо неё запись того, что ей отдали. */
const { frames } = vi.hoisted(() => ({ frames: [] as string[] }))
vi.mock('./three/Odontogram3D', () => ({
  Odontogram3D: ({ model, dim }: { model: Odontogram; dim: ReadonlySet<number> }) => {
    frames.push(`${model.teeth['16']!.state}/${model.bridges.length}`)
    return <div className="odo-stage" data-t16={model.teeth['16']!.state} data-dim={[...dim].sort().join(',')} />
  },
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
teeth['16'] = tooth(16, 'sus', { state: 'carie', sf: 'M', sfst: { M: 'carie' }, title: '16 · Carie' })

const VISITS = [
  { id: 7, date: '12.10.2026', label: '12.10.2026 · Consultație · Dr. Activ Doi', known: true },
  { id: 3, date: '01.09.2026', label: '01.09.2026 · Control · Dr. Activ Doi', known: false },
]

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
  patient: { id: 5, name: 'Odonto Compar', primary_doctor: '' },
  doctors: ['Dr. Activ Doi'],
  visits: VISITS,
}

/* визит 7: 16 был здоров (стал кариес), 21 был под коронкой, стоял мост 21–23 */
const CMP7: Compare = {
  visit: VISITS[0]!, known: true, since: '20.09.2026', milk_open: false,
  changes: [{ n: 16, was: 'Sănătos', now: 'Carie (M)' }, { n: 21, was: 'Coroană', now: 'Sănătos' }],
  teeth: {
    '16': tooth(16, 'sus', { title: '16 · Sănătos', svg: { frontal: svgOf(16, 'was'), occlusal: svgOf(16, 'was') } }),
    '21': tooth(21, 'sus', { state: 'coroana', title: '21 · Coroană', svg: { frontal: svgOf(21, 'was'), occlusal: svgOf(21, 'was') } }),
  },
  bridges: [{ id: 4, teeth: [[21, 'stalp'], [22, 'corp'], [23, 'stalp']], material: 'zirconiu', doctor: '' }],
  records: [],
}
/* визит 3 — до начала истории: состояния нет, есть строки летописи после него */
const CMP3: Compare = {
  visit: VISITS[1]!, known: false, since: '20.09.2026', milk_open: false, changes: [], teeth: {}, bridges: [],
  records: [{ n: 16, at: '03.10.2026', text: 'Dinte 16: Carie (M)' },
    { n: null, at: '02.10.2026', text: 'Punte dentară 21–23 ștearsă' },
    { n: 21, at: '01.10.2026', text: 'Dinte 21: Sănătos' }],
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })
let model = MODEL
/* ответ визита можно придержать: `held[id]` отпускает его */
const held: Record<number, () => void> = {}
let holdIds = new Set<number>()
function serve() {
  get.mockImplementation(async (url: string) => {
    const m = /\/odontogram\/compare\?visit=(\d+)$/.exec(url)
    if (!m) return ok(model)
    const id = Number(m[1])
    if (holdIds.has(id)) await new Promise<void>((done) => { held[id] = done })
    return ok(id === 7 ? CMP7 : CMP3)
  })
}
const compares = () => get.mock.calls.filter((c) => String(c[0]).includes('/compare')).map((c) => String(c[0]))

const btn = (n: number) => document.querySelector(`.odop .arch .tooth-btn[data-n="${n}"]`) as HTMLButtonElement
const mapBtn = (n: number) => document.querySelector(`.odop .dp-tm-btn[data-n="${n}"]`) as HTMLButtonElement
const pic = (n: number) => btn(n).querySelector('[data-pic]')?.getAttribute('data-pic')
const root = () => document.querySelector('.odop') as HTMLElement
const panel = () => document.querySelector('.dp-cmp') as HTMLElement | null
const cmpBtn = () => screen.getByRole('button', { name: 'Compară' }) as HTMLButtonElement
const open = () => openScreen('/admin/patient/:pid/odontograma', '/admin/patient/5/odontograma',
  <OdontogramScreen pid={5} />, loadOdontogram)
const ready = () => waitFor(() => expect(btn(16)).toBeTruthy())
const opened = async () => {
  fireEvent.click(cmpBtn())
  await waitFor(() => expect(within(panel()!).getByText(/dinți modificați/)).toBeTruthy())
}

beforeEach(() => {
  model = MODEL
  holdIds = new Set()
  frames.length = 0
  serve()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Compară: выбор визита и слой «было/стало»', () => {
  it('открывает последний визит с данными; изменившиеся отмечены, прочие гаснут; «Era» — рисунок сервера на ту дату, «Acum» — нынешний', async () => {
    open()
    await ready()
    await opened()
    expect(compares()).toEqual(['/patients/5/odontogram/compare?visit=7'])
    expect(root().hasAttribute('data-cmp')).toBe(true)
    expect(document.querySelector('.dp-tp:not(.dp-cmp)')).toBeNull()           // панели зуба нет
    const rows = within(panel()!).getAllByRole('button', { name: /→|Sănătos|Carie|Coroană/ })
      .filter((b) => b.classList.contains('dp-cmp-row'))
    expect(rows.map((b) => b.textContent)).toEqual(['16SănătosCarie (M)', '21CoroanăSănătos'])
    /* «Era»: изменившиеся зубы — рисунок той даты, неизменившиеся — сохранённые */
    expect(pic(16)).toBe('was')
    expect(pic(21)).toBe('was')
    expect(pic(11)).toBe('saved')
    expect(btn(16).className).not.toContain('dim')
    expect(btn(21).className).not.toContain('dim')
    expect(btn(11).className).toContain('dim')
    expect(mapBtn(11).className).toContain('dim')
    expect(mapBtn(16).getAttribute('title') ?? mapBtn(16).getAttribute('aria-label')).toContain('Sănătos')
    /* «Acum»: нынешние рисунки, отметки остаются */
    fireEvent.click(within(panel()!).getByRole('button', { name: /^Acum/ }))
    expect(pic(16)).toBe('saved')
    expect(pic(21)).toBe('saved')
    expect(btn(11).className).toContain('dim')
    fireEvent.click(within(panel()!).getByRole('button', { name: /^Era · 12\.10\.2026/ }))
    expect(pic(16)).toBe('was')
  })

  it('3D: сцене отдана карта визита (зуб и мост той даты) и гашение неизменившихся', async () => {
    localStorage.setItem('dp_odo_view', '3d')
    open()
    await waitFor(() => expect(document.querySelector('.odo-stage')).toBeTruthy())
    expect(frames.at(-1)).toBe('carie/0')
    fireEvent.click(cmpBtn())
    await waitFor(() => expect(frames.at(-1)).toBe('ok/1'))                     // было: 16 здоров, мост стоял
    const stage = document.querySelector('.odo-stage') as HTMLElement
    expect(stage.dataset.dim!.split(',')).not.toContain('16')
    expect(stage.dataset.dim!.split(',')).toContain('11')
    fireEvent.click(within(panel()!).getByRole('button', { name: /^Acum/ }))
    expect(frames.at(-1)).toBe('carie/0')
    fireEvent.click(within(panel()!).getByRole('button', { name: 'Închide comparația' }))
    expect(frames.at(-1)).toBe('carie/0')
    expect((document.querySelector('.odo-stage') as HTMLElement).dataset.dim).toBe('')
  })

  it('визит без истории — «нет данных» с датой начала; строки летописи после визита дословно, их зубы отмечены; рисунка «было» нет', async () => {
    open()
    await ready()
    await opened()
    fireEvent.change(within(panel()!).getByLabelText('Vizita'), { target: { value: '3' } })
    expect(await within(panel()!).findByText(
      'Nu există stare salvată a dinților pentru 01.09.2026: istoricul formulei dentare se păstrează din 20.09.2026.')).toBeTruthy()
    expect(compares().at(-1)).toBe('/patients/5/odontogram/compare?visit=3')
    expect(within(panel()!).getByText('Înregistrări după vizită (3)')).toBeTruthy()
    expect([...panel()!.querySelectorAll('.dp-cmp-rec')].map((li) => li.textContent))
      .toEqual(['03.10.2026Dinte 16: Carie (M)', '02.10.2026Punte dentară 21–23 ștearsă', '01.10.2026Dinte 21: Sănătos'])
    expect(pic(16)).toBe('saved')                                             // картинки «было» нет
    expect(pic(21)).toBe('saved')
    expect(btn(16).className).not.toContain('dim')                            // зубы со строками отмечены
    expect(btn(21).className).not.toContain('dim')
    expect(btn(11).className).toContain('dim')
    expect(within(panel()!).queryByRole('button', { name: /^Acum/ })).toBeNull()
    /* в списке визит без данных подписан */
    expect(within(panel()!).getByRole('option', { name: /01\.09\.2026.*fără date/ })).toBeTruthy()
  })

  it('поздний ответ прежнего визита ложится мимо: виден выбранный', async () => {
    holdIds = new Set([7])
    open()
    await ready()
    fireEvent.click(cmpBtn())
    await waitFor(() => expect(held[7]).toBeTruthy())
    fireEvent.change(within(panel()!).getByLabelText('Vizita'), { target: { value: '3' } })
    expect(await within(panel()!).findByText(/Nu există stare salvată/)).toBeTruthy()
    await act(async () => { held[7]!() })
    expect(within(panel()!).getByText(/Nu există stare salvată/)).toBeTruthy()
    expect(pic(16)).toBe('saved')
  })
})

describe('Compară: правка выключена, слой не в печать', () => {
  it('щелчок по зубу только подсвечивает его строку; меню и буквы молчат; Esc закрывает, панель зуба возвращается', async () => {
    open()
    await ready()
    await opened()
    fireEvent.click(btn(21))
    expect(document.querySelector('.dp-tp:not(.dp-cmp)')).toBeNull()
    expect(panel()!.querySelector('.dp-cmp-row[data-n="21"]')!.getAttribute('aria-current')).toBe('true')
    expect(btn(21).className).toContain('sel')
    fireEvent.contextMenu(btn(16), { clientX: 300, clientY: 200 })
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.keyDown(btn(21), { key: 'O' })
    fireEvent.keyDown(btn(21), { key: 'Enter' })
    expect(post).not.toHaveBeenCalled()
    expect((screen.getByRole('button', { name: 'Punte nouă' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.keyDown(root(), { key: 'Escape' })
    expect(panel()).toBeNull()
    expect(root().hasAttribute('data-cmp')).toBe(false)
    expect(document.querySelector('.dp-tp')).toBeTruthy()
    expect(pic(16)).toBe('saved')
    expect(btn(11).className).not.toContain('dim')
  })

  it('кнопка выключена с черновиком (причина в подсказке) и без прошлых визитов', async () => {
    post.mockImplementation(async (url: string, body: { teeth: { n: number; state: string }[] }) => {
      if (String(url).endsWith('/odontogram/preview')) return ok({ teeth: Object.fromEntries(body.teeth.map((d) => [String(d.n), { ...MODEL.teeth[String(d.n)]!, state: d.state }])) })
      throw new Error('нет подмены')
    })
    open()
    await ready()
    expect(cmpBtn().disabled).toBe(false)
    fireEvent.contextMenu(btn(11), { clientX: 300, clientY: 200 })
    fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitemradio', { name: 'Coroană' }))
    await waitFor(() => expect(cmpBtn().disabled).toBe(true))
    expect(cmpBtn().title).toBe('Salvați sau renunțați la modificări înainte de a compara')
    cleanup()
    model = { ...MODEL, visits: [] }
    open()
    await ready()
    expect(cmpBtn().disabled).toBe(true)
    expect(cmpBtn().title).toBe('Nicio vizită anterioară cu care să comparați')
  })

  it('печать при открытом «Era» закрывает сравнение и печатает сохранённое', async () => {
    let atPrint: (string | null | undefined)[] = []
    window.print = vi.fn(() => { atPrint = [pic(16), pic(21), String(Boolean(panel())), String(btn(11).className.includes('dim'))] })
    open()
    await ready()
    await opened()
    expect(pic(16)).toBe('was')
    fireEvent.click(screen.getByRole('button', { name: 'Printează' }))
    await waitFor(() => expect(window.print).toHaveBeenCalledTimes(1))
    expect(atPrint).toEqual(['saved', 'saved', 'false', 'false'])
  })
})
