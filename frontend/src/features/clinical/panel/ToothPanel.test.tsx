import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../../services/api'
import { openScreen } from '../../../test/openScreen'
import { loadOdontogram, OdontogramScreen } from '../OdontogramScreen'
import type { Odontogram, ToothInfo, ToothPlanItem } from '../chart'

/* Панель «Dintele N» по макету B (24.10): вкладки, крупный зуб вместо креста
   MODVL, позиции плана ЗУБА. Экран — целиком (черновик и кисть живут в
   useChart, клавиши — на рабочем столе), сеть подменена. */
vi.mock('../three/loadThree', () => ({
  loadThree: () => Promise.reject(new Error('nu')),
  assetVer: () => '',
  threeUrl: () => '/static/js/three.js',
  resetThree: () => undefined,
}))
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

/* рисунок сервера вида сверху: пять целей поверхностей `data-s` */
const occ = (n: number) =>
  `<svg class='tooth-svg tooth-occ' aria-label='${n}'><path d='M0 0'/><g class='sfz'>${['M', 'O', 'D', 'V', 'L'].map((s) => `<rect data-s='${s}'/>`).join('')}</g></svg>`

function tooth(n: number, jaw: 'sus' | 'jos', extra: Partial<ToothInfo> = {}): ToothInfo {
  return {
    jaw, mez: [1, 4].includes(Math.floor(n / 10)) ? 'right' : 'left', state: 'ok', note: '', doctor: '', at: '', sf: '', sfx: '', sfst: {}, mk: [], mkx: '',
    milk: n > 50, title: `${n} · Sănătos`, bridge: null, svg: { frontal: occ(n), occlusal: occ(n) }, name: 'Molar I', side: 'dreapta', ...extra,
  }
}

const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const teeth: Record<string, ToothInfo> = {}
for (const n of UPPER) teeth[String(n)] = tooth(n, 'sus')
for (const n of LOWER) teeth[String(n)] = tooth(n, 'jos')
teeth['16'] = tooth(16, 'sus', { state: 'carie', sf: 'MO', sfst: { M: 'carie', O: 'obturatie' }, note: 'distal', doctor: 'Dr. Activ Doi' })

const row = (id: number, procedure: string, status: string, label: string, extra: Partial<ToothPlanItem> = {}): ToothPlanItem => ({
  id, procedure, status, label, doctor: '', price: null, due: '', overdue: false, done: '', motiv: '',
  active: status === 'planificat' || status === 'in_lucru', ...extra,
})

const PLAN: Record<string, ToothPlanItem[]> = {
  '16': [
    row(4, 'Endodonție 16', 'in_lucru', 'În lucru', { doctor: 'Dr. Activ Doi', price: 1500 }),
    row(3, 'Obturație 16 MO', 'planificat', 'Planificat', { due: '20.10.2026', overdue: true, price: 800 }),
    row(2, 'Coroană 16', 'finalizat', 'Finalizat', { done: '01.10.2026' }),
    row(1, 'Implant 16', 'refuzat', 'Refuzat', { done: '02.10.2026', motiv: 'refuză implantul' }),
  ],
}

const MODEL: Odontogram = {
  teeth,
  history: { '16': [{ at: '18.09.2026', text: 'Dinte 16: Carie (MO)' }, { at: '19.09.2026', text: 'Dinte 16: Obturație (O)' }] },
  plan: PLAN,
  arches: { upper: UPPER, lower: LOWER, milk_upper: [], milk_lower: [] },
  arc: { upper: UPPER.map(() => 0), lower: LOWER.map(() => 0), milk_upper: [], milk_lower: [] },
  milk_open: false,
  bridges: [],
  legend: { frontal: [], occlusal: [] },
  states: { ok: 'Sănătos', carie: 'Carie', obturatie: 'Obturație', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' },
  tooth_states: { ok: 'Sănătos', coroana: 'Coroană', implant: 'Implant', extras: 'Extras', lipsa: 'Lipsă' },
  palette: { ok: '#64748B', carie: '#EF4444', obturatie: '#3B82F6', coroana: '#F59E0B', implant: '#8B5CF6', extras: '#64748B', lipsa: '#CBD5E1' },
  marks: { tratament: 'În tratament', devital: 'Nerv extras' },
  surfaces: { M: 'mezial', O: 'ocluzal', D: 'distal', V: 'vestibular', L: 'lingual' },
  surface_states: ['carie', 'obturatie'],
  bridge_roles: { stalp: 'Stâlp', corp: 'Corp de punte' },
  materials: [],
  patient: { id: 5, name: 'Odonto Pin', primary_doctor: '' },
  doctors: ['Dr. Activ Doi'],
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const panel = () => document.querySelector('.insp') as HTMLElement
const tab = (name: string) => within(panel()).getByRole('tab', { name: new RegExp(`^${name}`) })
const selected = () => within(panel()).getAllByRole('tab').find((t) => t.getAttribute('aria-selected') === 'true')
const big = () => panel().querySelector('.dp-bt') as HTMLElement
const btn = (n: number) => document.querySelector(`.odop .arch .tooth-btn[data-n="${n}"]`) as HTMLButtonElement
const open = (t?: number) => openScreen(
  '/admin/patient/:pid/odontograma', `/admin/patient/5/odontograma${t !== undefined ? `?t=${t}` : ''}`,
  <OdontogramScreen pid={5} />, loadOdontogram)

beforeEach(() => {
  get.mockResolvedValue(ok(MODEL))
})
afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('панель «Dintele N»: вкладки', () => {
  it('пять вкладок по порядку, «Suprafețe» первой; щелчок открывает свою, вкладка держится от зуба к зубу', async () => {
    open(16)
    await waitFor(() => expect(btn(16)).toBeTruthy())
    expect(within(panel()).getAllByRole('tab').map((t) => t.getAttribute('data-tab'))).toEqual(['sf', 'dg', 'tr', 'nt', 'is'])
    expect(selected()?.textContent).toBe('Suprafețe')
    expect(within(panel()).getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(selected()?.id)
    expect(within(panel()).getByText('Dintele 16')).toBeTruthy()
    fireEvent.click(tab('Diagnostic'))
    expect(within(panel()).getByRole('group', { name: 'Starea dintelui' })).toBeTruthy()
    expect(within(panel()).queryByRole('group', { name: 'Pensulă' })).toBeNull()      // другие вкладки не смонтированы
    fireEvent.click(btn(21))
    expect(selected()?.textContent).toBe('Diagnostic')                                  // врач идёт по челюсти той же вкладкой
    expect(within(panel()).getByText('Dintele 21')).toBeTruthy()
  })

  it('клавиатура: ←/→ по кругу и Home/End с фокусом; стрелки и Enter на вкладке — её, не рабочего стола', async () => {
    open(16)
    await waitFor(() => expect(tab('Suprafețe')).toBeTruthy())
    expect(tab('Suprafețe').tabIndex).toBe(0)
    expect(tab('Istoric').tabIndex).toBe(-1)                                            // одна остановка Tab на полосу
    fireEvent.keyDown(tab('Suprafețe'), { key: 'ArrowLeft' })
    expect(selected()?.textContent).toMatch(/^Istoric/)
    expect(document.activeElement).toBe(tab('Istoric'))
    fireEvent.keyDown(tab('Istoric'), { key: 'ArrowRight' })
    expect(selected()?.textContent).toBe('Suprafețe')
    fireEvent.keyDown(tab('Suprafețe'), { key: 'End' })
    expect(selected()?.textContent).toMatch(/^Istoric/)
    fireEvent.keyDown(tab('Istoric'), { key: 'Home' })
    expect(selected()?.textContent).toBe('Suprafețe')
    expect(btn(16).className).toContain('sel')                                          // ← и → не увели выбор к соседу
    fireEvent.keyDown(tab('Suprafețe'), { key: 'ArrowDown' })
    expect(btn(16).className).toContain('sel')                                          // ↓ — не другая челюсть
    /* черновик есть, а Enter на вкладке — не «записать» */
    fireEvent.click(within(panel()).getByRole('button', { name: /^Carie/ }))
    fireEvent.click(within(panel()).getByRole('button', { name: /^D distal$/ }))
    expect(screen.getByText('Modificări nesalvate')).toBeTruthy()
    fireEvent.keyDown(tab('Suprafețe'), { key: 'Enter' })
    expect(post).not.toHaveBeenCalled()
  })

  it('счётчики: у «Tratament» — позиции, что ждут работы, у «Istoric» — строки летописи; у пустых — без значка', async () => {
    open(16)
    await waitFor(() => expect(tab('Tratament')).toBeTruthy())
    expect(tab('Tratament').querySelector('.dp-pt-n')?.textContent).toBe('2')
    expect(tab('Istoric').querySelector('.dp-pt-n')?.textContent).toBe('2')
    expect(tab('Suprafețe').querySelector('.dp-pt-n')).toBeNull()
    fireEvent.click(btn(21))
    expect(tab('Tratament').querySelector('.dp-pt-n')).toBeNull()
    expect(tab('Istoric').querySelector('.dp-pt-n')).toBeNull()
  })

  it('«Salvează» и строка состояния — внизу на каждой вкладке', async () => {
    open(16)
    await waitFor(() => expect(tab('Suprafețe')).toBeTruthy())
    for (const name of ['Suprafețe', 'Diagnostic', 'Tratament', 'Notițe', 'Istoric']) {
      fireEvent.click(tab(name))
      expect(within(panel()).getByRole('button', { name: 'Salvează' })).toBeTruthy()
    }
  })
})

describe('панель: «Tratament» — план ЗУБА', () => {
  it('позиции зуба только чтением: порядок сервера, подпись статуса, срок с просрочкой, закрытые приглушены, причина отказа', async () => {
    open(16)
    await waitFor(() => expect(tab('Tratament')).toBeTruthy())
    fireEvent.click(tab('Tratament'))
    const rows = [...panel().querySelectorAll('.dp-tpl-r')] as HTMLElement[]
    expect(rows.map((r) => [r.querySelector('.pr')?.textContent, r.querySelector('.pbadge')?.textContent, r.className.includes('off')])).toEqual([
      ['Endodonție 16', 'În lucru', false],
      ['Obturație 16 MO', 'Planificat', false],
      ['Coroană 16', 'Finalizat', true],
      ['Implant 16', 'Refuzat', true],
    ])
    expect(rows[0]?.querySelector('.mt')?.textContent).toBe('Dr. Activ Doi · 1 500 MDL')
    expect(rows[1]?.querySelector('.dp-overdue')?.textContent).toContain('20.10.2026')
    expect(rows[2]?.querySelector('.mt')?.textContent).toContain('01.10.2026')
    expect(rows[3]?.querySelector('.pmotiv')?.textContent).toBe('refuză implantul')
    // переходов здесь нет — они у плана фиши, туда ссылка
    expect(within(panel()).queryByRole('button', { name: /Începe|Finalizează|Refuz/ })).toBeNull()
    expect(within(panel()).getByRole('link', { name: 'Planul complet în fișă' }).getAttribute('href')).toBe('/admin/patient/5?tab=plan')
    expect(within(panel()).getByRole('button', { name: 'Adaugă în plan' })).toBeTruthy()
    fireEvent.click(btn(21))
    expect(within(panel()).getByText('Nimic planificat pentru acest dinte')).toBeTruthy()
  })

  it('модель без поля плана (старый сервер) — пусто, без падения', async () => {
    const { plan: _drop, ...bare } = MODEL
    void _drop
    get.mockResolvedValue(ok(bare as Odontogram))
    open(16)
    await waitFor(() => expect(tab('Tratament')).toBeTruthy())
    expect(tab('Tratament').querySelector('.dp-pt-n')).toBeNull()
    fireEvent.click(tab('Tratament'))
    expect(within(panel()).getByText('Nimic planificat pentru acest dinte')).toBeTruthy()
  })
})

describe('панель: крупный зуб вместо креста MODVL', () => {
  it('рисунок сервера вида сверху; буквы по сторонам рисунка: у верхней V сверху и P снизу, у нижней наоборот; M — со стороны `mez`', async () => {
    open(16)
    await waitFor(() => expect(big()).toBeTruthy())
    expect(big().querySelector(".dp-bt-pic svg[aria-label='16']")).toBeTruthy()
    const at = () => Object.fromEntries([...big().querySelectorAll('.dp-bt-l')].map((l) => [l.textContent, l.className.split(' ')[1]]))
    expect(at()).toEqual({ V: 't', P: 'b', M: 'r', D: 'l' })                            // 16: mez right
    fireEvent.click(btn(36))
    expect(at()).toEqual({ V: 'b', L: 't', M: 'l', D: 'r' })                            // 36: нижняя дуга перевёрнута, mez left
    expect(panel().querySelector('.dp-sfx')).toBeNull()                                 // креста MODVL больше нет
  })

  it('поле крупного зуба — та же пара жестов: без кисти выбор, с кистью краска; черновик виден поверх сохранённого', async () => {
    open(16)
    await waitFor(() => expect(big()).toBeTruthy())
    const field = (s: string) => big().querySelector(`[data-s='${s}']`) as Element
    const sfRow = (s: string) => panel().querySelector(`.dp-sfl-r[data-sf='${s}']`) as HTMLElement
    expect(big().getAttribute('data-sel')).toBe('M')                                    // первая отмеченная
    fireEvent.click(field('D'))
    expect(big().getAttribute('data-sel')).toBe('D')
    expect(sfRow('D').className).toContain('on')
    expect(screen.queryByText('Modificări nesalvate')).toBeNull()                      // без кисти — только выбор
    expect(big().style.getPropertyValue('--bt-D')).toBe('')                             // рисунок как записан
    fireEvent.click(within(panel()).getByRole('button', { name: /^Carie/ }))
    fireEvent.click(field('D'))                                                         // D: — → carie
    expect(sfRow('D').className).toContain('sf-carie')
    expect(big().style.getPropertyValue('--bt-D')).toBe('#EF4444')                     // цвет палитры сервера
    fireEvent.click(field('O'))                                                         // O: obturatie → carie (перекраска)
    expect(big().style.getPropertyValue('--bt-O')).toBe('#EF4444')
    fireEvent.click(field('O'))                                                         // та же кисть — снять: поле «стёрто»
    expect(big().style.getPropertyValue('--bt-O')).toBe('var(--bt-clear)')
    expect(big().style.getPropertyValue('--bt-M')).toBe('')                             // M не трогали — его рисует сервер
    expect(screen.getByText('Modificări nesalvate')).toBeTruthy()
    fireEvent.click(screen.getByText('Renunță'))
    expect(['M', 'O', 'D'].map((s) => big().style.getPropertyValue(`--bt-${s}`))).toEqual(['', '', ''])
  })

  it('состояние зуба в черновике не то, что нарисовано, — рисунок гаснет и говорит, что будет после записи', async () => {
    open(21)
    await waitFor(() => expect(big()).toBeTruthy())
    expect(big().className).not.toContain('stale')
    fireEvent.click(tab('Diagnostic'))
    fireEvent.click(within(panel()).getByRole('button', { name: 'Coroană' }))
    fireEvent.click(tab('Suprafețe'))
    expect(big().className).toContain('stale')
    expect(within(panel()).getByText('Desenul arată starea salvată. După „Salvează”: Coroană')).toBeTruthy()
    expect((within(panel()).getByRole('button', { name: /^Carie/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('без правки «Salvează» выключена (сервер пишет летопись на каждую запись); правка на одной вкладке пишется с любой — намерение целиком', async () => {
    post.mockResolvedValueOnce(ok(MODEL, 'ok_card', 'Fișa pacientului a fost actualizată'))
    open(16)
    await waitFor(() => expect(tab('Istoric')).toBeTruthy())
    const save = () => within(panel()).getByRole('button', { name: 'Salvează' }) as HTMLButtonElement
    for (const name of ['Suprafețe', 'Diagnostic', 'Tratament', 'Notițe', 'Istoric']) {
      fireEvent.click(tab(name))
      expect(save().disabled).toBe(true)
    }
    fireEvent.click(tab('Notițe'))
    fireEvent.change(within(panel()).getByLabelText('Notiță (opțional)'), { target: { value: 'distal, verificat' } })
    fireEvent.click(tab('Istoric'))                                                     // правка переживает смену вкладки
    expect(save().disabled).toBe(false)
    fireEvent.click(save())
    expect(await screen.findByText('Fișa pacientului a fost actualizată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/patients/5/teeth', { teeth: [expect.objectContaining({
      n: 16, state: 'carie', state0: 'carie', note: 'distal, verificat', doctor: 'Dr. Activ Doi',
      surfaces: { M: 'carie', O: 'obturatie' }, marks: [],
    })] })
  })
})
