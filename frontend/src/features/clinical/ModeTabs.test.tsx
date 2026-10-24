import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { dimmedTeeth, legendCounts, modeCount, modeSet, screenDim, type ChartMode, type Odontogram, type PerioLayer, type ToothInfo } from './chart'
import { ModeTabs } from './ModeTabs'
import { OdontogramWorkbench } from './OdontogramWorkbench'
import { ToothMenu } from './ToothMenu'

/* Режимы рабочего стола (Олег 24.10, макет B): вкладки шапки — фильтр ЭКРАНА
   по словарю сервера. Режим задаёт набор зубов, легенда сужает внутри него,
   выбор режима снимает легенду; меню зуба ставит пункты режима первыми.
   three.js в jsdom нет — загрузчик отказывает, как в OdontogramScreen.test. */
vi.mock('./three/loadThree', () => ({
  loadThree: () => Promise.reject(new Error('nu')),
  assetVer: () => '',
  threeUrl: () => '/static/js/three.js',
  resetThree: () => undefined,
}))

const svgOf = (n: number) => `<svg class='tooth-svg' aria-label='${n}'><g class='sfz'><circle data-s='M'/><circle data-s='O'/></g></svg>`

function tooth(n: number, extra: Partial<ToothInfo> = {}): ToothInfo {
  return {
    jaw: n < 30 ? 'sus' : 'jos', mez: 'right', state: 'ok', note: '', doctor: '', at: '', sf: '', sfx: '', sfst: {}, mk: [], mkx: '',
    milk: false, title: `${n} · Sănătos`, bridge: null, svg: { frontal: svgOf(n), occlusal: svgOf(n) }, ...extra,
  }
}

const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const teeth: Record<string, ToothInfo> = {}
for (const n of [...UPPER, ...LOWER]) teeth[String(n)] = tooth(n)
teeth['16'] = tooth(16, { state: 'carie', sf: 'MO', sfst: { M: 'carie', O: 'obturatie' } })
teeth['26'] = tooth(26, { state: 'coroana' })
teeth['36'] = tooth(36, { state: 'implant' })
teeth['46'] = tooth(46, { state: 'extras', bridge: { role: 'corp', material: '' } })
teeth['47'] = tooth(47, { bridge: { role: 'stalp', material: '' } })
teeth['45'] = tooth(45, { bridge: { role: 'stalp', material: '' } })
teeth['11'] = tooth(11, { mk: ['devital'] })

/* словарь — как у сервера (`odontogram.MODES`) */
const MODES: ChartMode[] = [
  { key: 'examinare', label: 'Examinare', kind: 'all', keys: [], bridges: false },
  { key: 'carii', label: 'Carii', kind: 'keys', keys: ['carie'], bridges: false },
  { key: 'restaurare', label: 'Restaurare', kind: 'keys', keys: ['obturatie', 'coroana'], bridges: false },
  { key: 'endo', label: 'Endodonție', kind: 'keys', keys: ['devital', 'tratament'], bridges: false },
  { key: 'paro', label: 'Parodonțiu', kind: 'perio', keys: [], bridges: false },
  { key: 'chirurgie', label: 'Chirurgie', kind: 'keys', keys: ['extras', 'lipsa'], bridges: false },
  { key: 'implant', label: 'Implant', kind: 'keys', keys: ['implant'], bridges: false },
  { key: 'proteza', label: 'Proteză', kind: 'keys', keys: ['coroana'], bridges: true },
]
const mode = (k: string) => MODES.find((m) => m.key === k)!

const STATES = { ok: 'Sănătos', carie: 'Carie', obturatie: 'Obturație', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' }
const MARKS = { tratament: 'În tratament', devital: 'Nerv extras' }
const PALETTE = {
  ok: '#94A3B8', carie: '#EF4444', obturatie: '#3B82F6', coroana: '#F59E0B', implant: '#8B5CF6', extras: '#64748B', lipsa: '#CBD5E1',
  tratament: '#16A34A', devital: '#BE185D',
}
const legend = Object.entries({ ...STATES, ...MARKS }).filter(([k]) => k !== 'ok')
  .map(([key, label]) => ({ kind: key in MARKS ? 'mark' as const : 'state' as const, key, label, svg: '<svg></svg>' }))

const MODEL: Odontogram = {
  teeth,
  history: {},
  arches: { upper: UPPER, lower: LOWER, milk_upper: [], milk_lower: [] },
  arc: { upper: UPPER.map(() => 0), lower: LOWER.map(() => 0), milk_upper: [], milk_lower: [] },
  milk_open: false,
  bridges: [{ id: 1, teeth: [[47, 'stalp'], [46, 'corp'], [45, 'stalp']], material: '', doctor: '' }],
  legend: { frontal: legend, occlusal: legend },
  states: STATES,
  tooth_states: { ok: 'Sănătos', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' },
  palette: PALETTE,
  marks: MARKS,
  surfaces: { M: 'mezial', O: 'ocluzal', D: 'distal', V: 'vestibular', L: 'lingual' },
  surface_states: ['carie', 'obturatie'],
  bridge_roles: { stalp: 'Stâlp', corp: 'Corp de punte' },
  materials: [{ id: 'alt', label: 'Alt material…' }],
  modes: MODES,
  patient: { id: 5, name: 'Mod Test', primary_doctor: '' },
  doctors: [],
}

const LAYER: PerioLayer = {
  exam: { id: 7, at: '18.09.2026' },
  rows: {
    '16': { tooth: 16, pd: [2, 3, 5, 3, 2, 3], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [2, 3, 5, 3, 2, 3] },
    '17': { tooth: 17, pd: [2, 2, 2, 2, 2, 2], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [2, 2, 2, 2, 2, 2] },
  },
  limits: { deep: 4, severe: 6 },
  colors: { deep: '#F59E0B', severe: '#DC2626' },
  sites: [],
  grades: { mob: {}, furc: {} },
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('словарь режимов: набор, число, гашение', () => {
  it('«keys» — по ключам легенды и мостам; «all» и «perio» набора не сужают', () => {
    expect(modeSet(MODEL, mode('examinare'))).toBeNull()
    expect(modeSet(MODEL, mode('paro'))).toBeNull()
    expect(modeSet(MODEL, null)).toBeNull()
    expect([...modeSet(MODEL, mode('carii'))!]).toEqual([16])
    // пломба на поверхности — тоже «реставрация»
    expect([...modeSet(MODEL, mode('restaurare'))!].sort()).toEqual([16, 26])
    expect([...modeSet(MODEL, mode('proteza'))!].sort()).toEqual([26, 45, 46, 47])
    expect([...modeSet(MODEL, mode('endo'))!]).toEqual([11])
  })

  it('число у вкладки: зубы на экране; у пародонта — с карманом от порога сервера; у «всё видно» числа нет', () => {
    expect(modeCount(MODEL, mode('examinare'))).toBeNull()
    expect(modeCount(MODEL, mode('carii'))).toBe(1)
    expect(modeCount(MODEL, mode('proteza'))).toBe(4)
    expect(modeCount(MODEL, mode('chirurgie'))).toBe(1)
    expect(modeCount(MODEL, mode('paro'))).toBe(0)
    expect(modeCount({ ...MODEL, perio_layer: LAYER }, mode('paro'))).toBe(1)
  })

  it('режим задаёт набор, легенда сужает внутри; без режима — прежняя легенда', () => {
    const all = Object.keys(MODEL.teeth).length
    const carii = screenDim(MODEL, mode('carii'), null)
    expect(carii.has(16)).toBe(false)
    expect(carii.size).toBe(all - 1)
    const narrowed = screenDim(MODEL, mode('restaurare'), 'coroana')
    expect(narrowed.has(26)).toBe(false)
    expect(narrowed.has(16)).toBe(true)                     // в наборе, но не про пункт легенды
    expect(narrowed.size).toBe(all - 1)
    expect(screenDim(MODEL, mode('examinare'), 'carie')).toEqual(dimmedTeeth(MODEL, 'carie'))
    expect(screenDim(MODEL, mode('paro'), null).size).toBe(0)
    // счётчики легенды — внутри набора режима
    const within = legendCounts(MODEL, legend, modeSet(MODEL, mode('restaurare')))
    expect([within.carie, within.obturatie, within.coroana, within.implant]).toEqual([1, 1, 1, 0])
    expect(legendCounts(MODEL, legend).implant).toBe(1)
  })
})

describe('вкладки режимов', () => {
  const tabs = () => within(screen.getByRole('group', { name: 'Ce arată vederea' }))
  const tab = (k: string) => document.querySelector(`.dp-odo-modes [data-mode="${k}"]`) as HTMLButtonElement

  it('подписи и порядок — сервера; число, метки цвета палитры; пародонт без осмотра выключен и говорит почему', () => {
    const pick = vi.fn()
    render(<ModeTabs model={MODEL} value="carii" onPick={pick} />)
    expect(tabs().getAllByRole('button').map((b) => b.getAttribute('data-mode'))).toEqual(MODES.map((m) => m.key))
    expect(tab('carii').getAttribute('aria-pressed')).toBe('true')
    expect(tab('examinare').getAttribute('aria-pressed')).toBe('false')
    expect(tabs().getByRole('button', { name: 'Proteză 4' })).toBe(tab('proteza'))
    expect(tab('examinare').querySelector('.dp-mode-n')).toBeNull()
    expect(tab('restaurare').querySelectorAll('.dp-mode-sw i').length).toBe(2)
    expect((tab('carii').querySelector('.dp-mode-sw i') as HTMLElement).style.background).toBe('rgb(239, 68, 68)')
    expect(tab('restaurare').title).toBe('Arată dinții cu: Obturație, Coroană')
    expect(tab('proteza').title).toBe('Arată dinții cu: Coroană, punte')
    expect(tab('paro').disabled).toBe(true)
    expect(tab('paro').title).toBe('Pacientul nu are încă o parodontogramă cu măsurători')
    fireEvent.click(tab('implant'))
    expect(pick).toHaveBeenCalledWith('implant')
    cleanup()
    render(<ModeTabs model={{ ...MODEL, perio_layer: LAYER }} value="examinare" onPick={pick} />)
    expect(tab('paro').disabled).toBe(false)
    expect(tab('paro').title).toContain('18.09.2026')
    expect(tab('paro').querySelectorAll('.dp-mode-sw i').length).toBe(2)
  })

  it('без словаря в модели вкладок нет', () => {
    const bare: Odontogram = { ...MODEL }
    delete bare.modes
    render(<ModeTabs model={bare} value="" onPick={() => undefined} />)
    expect(document.querySelector('.dp-odo-modes')).toBeNull()
  })

  it('клавиатура: стрелки и Home/End ходят по включённым вкладкам; стрелки и Enter дальше рабочего стола не уходят', () => {
    const outer = vi.fn()
    render(<div onKeyDown={outer}><ModeTabs model={MODEL} value="examinare" onPick={() => undefined} /></div>)
    tab('examinare').focus()
    fireEvent.keyDown(tab('examinare'), { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tab('carii'))
    fireEvent.keyDown(tab('carii'), { key: 'End' })
    expect(document.activeElement).toBe(tab('proteza'))
    fireEvent.keyDown(tab('proteza'), { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tab('examinare'))     // по кругу
    fireEvent.keyDown(tab('examinare'), { key: 'End' })
    fireEvent.keyDown(tab('proteza'), { key: 'Home' })
    expect(document.activeElement).toBe(tab('examinare'))
    tab('endo').focus()
    fireEvent.keyDown(tab('endo'), { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tab('chirurgie'))     // выключенный пародонт пропущен
    // Enter не гасится: браузер нажмёт вкладку сам
    expect(fireEvent.keyDown(tab('chirurgie'), { key: 'Enter' })).toBe(true)
    expect(outer).not.toHaveBeenCalled()
    fireEvent.keyDown(tab('chirurgie'), { key: 'Escape' })
    expect(outer).toHaveBeenCalledTimes(1)                    // остальное — рабочему столу
  })
})

describe('меню зуба под режим', () => {
  const items = () => Array.from(document.querySelectorAll('.dp-cmenu [role^="menuitem"]')).map((b) => b.textContent?.trim())
  const mount = (m: ChartMode | null, n = 46) => render(
    <ToothMenu model={MODEL} at={{ n, x: 10, y: 10 }} current="ok" marks={[]} onState={() => undefined} onMark={() => undefined}
      onPlan={() => undefined} onBridge={() => undefined} onClose={() => undefined} mode={m} />)

  it('пункты режима — первыми, группа с ними — наверху; ничего не пропадает', () => {
    mount(null)
    const plain = items()
    expect(plain).toEqual(['Sănătos', 'Coroană', 'Implant', 'Extras', 'Lipsă', 'În tratament', 'Nerv extras',
      'Adaugă în plan', 'Punte nouă de la acest dinte'])
    expect(document.querySelector('.dp-cmenu-h')?.textContent).toBe('Dinte 46')
    cleanup()
    mount(mode('chirurgie'))
    expect(items()).toEqual(['Extras', 'Lipsă', 'Sănătos', 'Coroană', 'Implant', 'În tratament', 'Nerv extras',
      'Adaugă în plan', 'Punte nouă de la acest dinte'])
    expect(document.querySelector('.dp-cmenu-h')?.textContent).toBe('Dinte 46 · Chirurgie')
    cleanup()
    mount(mode('endo'))
    expect(items().slice(0, 2)).toEqual(['În tratament', 'Nerv extras'])
    cleanup()
    mount(mode('proteza'))
    expect(items()).toEqual(['Coroană', 'Sănătos', 'Implant', 'Extras', 'Lipsă', 'Punte nouă de la acest dinte',
      'Adaugă în plan', 'În tratament', 'Nerv extras'])
    expect(document.querySelectorAll('.dp-cmenu-sep').length).toBe(2)
    cleanup()
    // в режиме без пунктов меню (кариес ставится кистью) порядок прежний и шапка без режима
    mount(mode('carii'))
    expect(items()).toEqual(plain)
    expect(document.querySelector('.dp-cmenu-h')?.textContent).toBe('Dinte 46')
  })
})

describe('режимы на рабочем столе', () => {
  const mount = (model: Odontogram = MODEL) => render(
    <OdontogramWorkbench pid={5} model={model} replace={() => undefined} fail={() => undefined} say={() => undefined} />)
  const tab = (k: string) => document.querySelector(`.dp-odo-modes [data-mode="${k}"]`) as HTMLButtonElement
  const archDim = () => Array.from(document.querySelectorAll('.arch .tooth-btn.dim')).map((b) => Number(b.getAttribute('data-n')))
  const mapBtn = (n: number) => document.querySelector(`.dp-tm-btn[data-n="${n}"]`) as HTMLElement
  const leg = (label: string) => within(document.querySelector('.tleg') as HTMLElement).getByRole('button', { name: new RegExp(`^${label}`) })

  it('«Examinare» с открытия; режим гасит чужие зубы на дуге и в ряду; легенда сужает внутри; смена режима снимает легенду', () => {
    mount()
    expect(tab('examinare').getAttribute('aria-pressed')).toBe('true')
    expect(archDim()).toEqual([])
    fireEvent.click(tab('carii'))
    expect(tab('carii').getAttribute('aria-pressed')).toBe('true')
    expect(archDim().length).toBe(31)
    expect(archDim()).not.toContain(16)
    expect(mapBtn(16).classList.contains('dim')).toBe(false)
    expect(mapBtn(11).classList.contains('dim')).toBe(true)
    // счётчики легенды — внутри режима: коронки среди кариозных нет
    expect(leg('Carie').querySelector('.lg-n')?.textContent).toBe('1')
    expect(leg('Coroană').querySelector('.lg-n')).toBeNull()
    fireEvent.click(leg('Coroană'))
    expect(archDim().length).toBe(32)                          // пусто внутри набора — честно пусто
    fireEvent.click(tab('restaurare'))
    expect(document.querySelector('.tleg .dp-leg.on')).toBeNull()
    expect(archDim().sort()).toEqual(Object.keys(MODEL.teeth).map(Number).filter((n) => n !== 16 && n !== 26).sort())
    fireEvent.click(leg('Coroană'))
    expect(archDim()).toContain(16)
    expect(archDim()).not.toContain(26)
    fireEvent.click(tab('examinare'))
    expect(document.querySelector('.tleg .dp-leg.on')).toBeNull()
    expect(archDim()).toEqual([])
  })

  it('клавиатура на вкладке не двигает зуб и не съедает Enter; меню зуба — в порядке режима', () => {
    mount()
    fireEvent.click(document.querySelector('.arch .tooth-btn[data-n="16"]') as HTMLElement)
    expect(document.querySelector('.odop')?.getAttribute('data-sel')).toBe('16')
    tab('examinare').focus()
    fireEvent.keyDown(tab('examinare'), { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tab('carii'))
    expect(document.querySelector('.odop')?.getAttribute('data-sel')).toBe('16')
    expect(fireEvent.keyDown(tab('carii'), { key: 'Enter' })).toBe(true)
    fireEvent.click(tab('chirurgie'))
    fireEvent.contextMenu(document.querySelector('.arch .tooth-btn[data-n="46"]') as HTMLElement, { clientX: 100, clientY: 100 })
    const first = document.querySelector('.dp-cmenu [role="menuitemradio"]')
    expect(first?.textContent?.trim()).toBe('Extras')
  })

  it('«Parodonțiu» везёт в 3D и ничего не гасит; в 2D экран показывает «всё видно»', async () => {
    mount({ ...MODEL, perio_layer: LAYER })
    fireEvent.click(tab('carii'))
    fireEvent.click(tab('paro'))
    expect(document.querySelector('.odop')?.getAttribute('data-view')).toBe('3d')
    expect(tab('paro').getAttribute('aria-pressed')).toBe('true')
    await screen.findByText(/3D nu s-a încărcat/)
    fireEvent.click(screen.getByRole('button', { name: '2D' }))
    expect(document.querySelector('.odop')?.getAttribute('data-view')).toBe('frontal')
    expect(tab('examinare').getAttribute('aria-pressed')).toBe('true')
    expect(archDim()).toEqual([])
  })
})
