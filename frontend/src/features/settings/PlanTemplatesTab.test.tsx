import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { PlanTemplatesData, TemplatesData } from './settings'
import { openScreen } from '../../test/openScreen'
import { loadTemplatesSettings, TemplatesSettingsScreen } from './TemplatesSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const CONSULT: TemplatesData = {
  services: [], fields: [], marks: { tooth: '{dinte}', date: '{data}' },
  example: { acuze: '', examen: '', diagnostic: '', tratament: '', recomandari: '' }, general: [], max: 2000,
}
const SERVICES = [
  { id: 'consult', label: 'Consultație', price: 'gratuit' },
  { id: 'implant', label: 'Implant dentar', price: '9000–12000 MDL' },
  { id: 'crown', label: 'Coroană zirconiu', price: '4500 MDL' },
  { id: 'xray', label: 'Radiografie', price: '' },
]
const MAX = { name: 60, note: 120, rows: 40, price: 1000000, templates: 100 }
const IMPLANT = {
  id: 'pt1', name: 'Implant + coroană', note: 'pentru molari', rows: [
    { procedure: 'Consultație', service_id: 'consult', tooth: false, price: null },
    { procedure: 'Implant dentar', service_id: 'implant', tooth: true, price: null },
    { procedure: 'Coroană zirconiu', service_id: 'crown', tooth: true, price: 5000 },
  ],
}
const CANAL = {
  id: 'pt2', name: 'Tratament de canal + coroană', note: '', rows: [
    { procedure: 'Tratament endodontic', service_id: '', tooth: true, price: null },
  ],
}
const DATA: PlanTemplatesData = { templates: [IMPLANT, CANAL], services: SERVICES, created: [], max: MAX }

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const serve = (plan: PlanTemplatesData = DATA) => get.mockImplementation((path: string) =>
  Promise.resolve(ok(path === '/settings/templates' ? CONSULT : plan)))

const open = () => openScreen('/admin/settings/templates', '/admin/settings/templates?tab=plan',
  <TemplatesSettingsScreen />, loadTemplatesSettings)
const list = () => within(screen.getByRole('navigation', { name: 'Șabloanele clinicii' }))
const item = (name: RegExp) => list().getByRole('button', { name })
const nameInput = () => screen.getByLabelText('Nume') as HTMLInputElement
const proc = (n: number) => screen.getByLabelText(`Procedura rândului ${n}`) as HTMLSelectElement
const price = (n: number) => screen.getByLabelText(`Prețul rândului ${n}`) as HTMLInputElement
const tooth = (n: number, label: string) =>
  within(screen.getByRole('group', { name: `Dintele rândului ${n}` })).getByRole('button', { name: label })
const btn = (name: RegExp | string) => screen.getByRole('button', { name }) as HTMLButtonElement
const saveBtn = () => btn(/Salvează șabloanele/)
const procs = () => screen.getAllByLabelText(/^Procedura rândului/).map((s) => {
  const el = s as HTMLSelectElement
  return el.selectedOptions[0]?.textContent ?? ''
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('PlanTemplatesTab — вкладка «Plan de tratament»', () => {
  it('адрес ?tab=plan открывает вкладку: список слева, первый шаблон в редакторе, сохранять нечего', async () => {
    serve()
    open()
    await screen.findByLabelText('Nume')
    expect(screen.getByRole('tab', { name: 'Plan de tratament' }).getAttribute('aria-selected')).toBe('true')
    expect(item(/Implant \+ coroană/).textContent).toMatch(/3 proceduri/)
    expect(item(/Tratament de canal/).textContent).toMatch(/1 procedură/)
    expect(item(/Implant \+ coroană/).getAttribute('aria-current')).toBe('true')
    expect(nameInput().value).toBe('Implant + coroană')
    expect(procs()).toEqual(['Consultație', 'Implant dentar', 'Coroană zirconiu'])
    expect(tooth(1, 'fără dinte').getAttribute('aria-pressed')).toBe('true')
    expect(tooth(2, 'cu dinte').getAttribute('aria-pressed')).toBe('true')
    /* пустая цена — «din listă» и цена прайса рядом словами клиники; своя цена — числом */
    expect(price(2).value).toBe('')
    expect(price(2).placeholder).toBe('din listă')
    expect(screen.getByText('în listă: 9000–12000 MDL')).toBeTruthy()
    expect(price(3).value).toBe('5000')
    expect(saveBtn().disabled).toBe(true)
    /* стрелки порядка и корзина — значками программы, не знаками шрифта */
    expect(btn('Mută mai sus: 2').querySelector('svg')).not.toBeNull()
    expect(document.body.textContent).not.toMatch(/[↑↓▲▼✕→]/)
  })

  it('строка свободным текстом показана как есть и помечена; выбор услуги даёт ей ключ', async () => {
    serve()
    post.mockResolvedValueOnce(ok(DATA, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByLabelText('Nume')
    fireEvent.click(item(/Tratament de canal/))
    expect(procs()).toEqual(['Tratament endodontic — nu este în lista de servicii'])
    expect(price(1).placeholder).toBe('fără preț')
    fireEvent.change(proc(1), { target: { value: 'xray' } })
    expect(procs()).toEqual(['Radiografie'])
    fireEvent.click(saveBtn())
    await screen.findByText('Setări salvate')
    expect(post).toHaveBeenCalledWith('/settings/plan-templates',
      { templates: { pt2: { rows: [{ service_id: 'xray', tooth: true, price: null }] } } })
  })

  it('⭐ на запись уходит только ТРОНУТОЕ: поле шаблона, а не весь; сосед — никак; возврат правки — не правка', async () => {
    serve()
    const after = { ...DATA, templates: [{ ...IMPLANT, note: 'frontali' }, CANAL] }
    post.mockResolvedValueOnce(ok(after, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByLabelText('Nume')
    fireEvent.change(nameInput(), { target: { value: 'Alt nume' } })
    expect(item(/Alt nume/).textContent).toMatch(/modificat/)
    fireEvent.change(nameInput(), { target: { value: 'Implant + coroană ' } })
    expect(item(/Implant \+ coroană/).textContent).not.toMatch(/modificat/)
    expect(saveBtn().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/^Notă/), { target: { value: 'frontali' } })
    expect(screen.getByRole('tab', { name: /Plan de tratament/ }).querySelector('.tpl-dirty')).not.toBeNull()
    fireEvent.click(saveBtn())
    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/plan-templates', { templates: { pt1: { note: 'frontali' } } })
    expect(item(/Implant \+ coroană/).textContent).not.toMatch(/modificat/)
    expect(saveBtn().disabled).toBe(true)
  })

  it('строки: порядок вверх и вниз, «cu dinte / fără dinte», цена только цифрами, удаление и новая строка', async () => {
    serve()
    post.mockResolvedValueOnce(ok(DATA, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByLabelText('Nume')
    expect(btn('Mută mai sus: 1').disabled).toBe(true)
    expect(btn('Mută mai jos: 3').disabled).toBe(true)
    fireEvent.click(btn('Mută mai jos: 1'))
    expect(procs()).toEqual(['Implant dentar', 'Consultație', 'Coroană zirconiu'])
    fireEvent.click(btn('Mută mai sus: 3'))
    expect(procs()).toEqual(['Implant dentar', 'Coroană zirconiu', 'Consultație'])
    fireEvent.click(tooth(1, 'fără dinte'))
    fireEvent.change(price(1), { target: { value: '9 500 lei' } })
    expect(price(1).value).toBe('9500')
    fireEvent.click(btn('Șterge rândul: 3'))
    fireEvent.click(btn(/Rând nou/))
    expect(procs()).toEqual(['Implant dentar', 'Coroană zirconiu', 'Alegeți procedura…'])
    fireEvent.change(proc(3), { target: { value: 'xray' } })
    fireEvent.click(saveBtn())
    await screen.findByText('Setări salvate')
    expect(post).toHaveBeenCalledWith('/settings/plan-templates', { templates: { pt1: { rows: [
      { service_id: 'implant', tooth: false, price: 9500 },
      { service_id: 'crown', tooth: true, price: 5000 },
      { service_id: 'xray', tooth: true, price: null },
    ] } } })
  })

  it('новый шаблон и копия: уходят в `new`, после записи выбран созданный', async () => {
    serve()
    const made = { id: 'pt3', name: 'Implant + coroană (copie)', note: 'pentru molari', rows: IMPLANT.rows }
    post.mockResolvedValueOnce(ok({ ...DATA, templates: [IMPLANT, CANAL, made], created: ['pt3'] }, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByLabelText('Nume')
    fireEvent.click(btn(/Copiază șablonul/))
    expect(nameInput().value).toBe('Implant + coroană (copie)')
    expect(item(/\(copie\)/).textContent).toMatch(/3 proceduri · nou/)
    expect(procs()).toEqual(['Consultație', 'Implant dentar', 'Coroană zirconiu'])
    fireEvent.click(saveBtn())
    await screen.findByText('Setări salvate')
    expect(post).toHaveBeenCalledWith('/settings/plan-templates', { new: [{
      name: 'Implant + coroană (copie)', note: 'pentru molari', rows: [
        { service_id: 'consult', tooth: false, price: null },
        { service_id: 'implant', tooth: true, price: null },
        { service_id: 'crown', tooth: true, price: 5000 },
      ] }] })
    expect(item(/\(copie\)/).getAttribute('aria-current')).toBe('true')
    expect(item(/\(copie\)/).textContent).not.toMatch(/nou/)
  })

  it('пустое имя, пустая строка, повтор имени — отказ на месте словами экрана, запроса нет', async () => {
    serve()
    open()
    await screen.findByLabelText('Nume')
    fireEvent.click(btn(/Șablon nou/))
    expect(nameInput().value).toBe('')
    fireEvent.click(saveBtn())
    expect(await screen.findByText('Scrieți numele șablonului.')).toBeTruthy()
    expect(nameInput().getAttribute('aria-invalid')).toBe('true')
    fireEvent.change(nameInput(), { target: { value: 'Igienizare completă' } })
    fireEvent.click(saveBtn())
    expect(await screen.findByText(/Alegeți procedura la fiecare rând/)).toBeTruthy()
    expect(proc(1).getAttribute('aria-invalid')).toBe('true')
    fireEvent.click(btn('Șterge rândul: 1'))
    fireEvent.click(saveBtn())
    expect((await screen.findAllByText('Șablonul are nevoie de cel puțin o procedură.')).length).toBeGreaterThan(0)
    fireEvent.click(btn(/Rând nou/))
    fireEvent.change(proc(1), { target: { value: 'consult' } })
    fireEvent.change(nameInput(), { target: { value: ' implant + COROANĂ' } })
    fireEvent.click(saveBtn())
    expect(await screen.findByText(/Există deja un șablon cu acest nume/)).toBeTruthy()
    expect(post).not.toHaveBeenCalled()
  })

  it('удаление — своим вопросом с именем шаблона; отказ ничего не шлёт, согласие шлёт только `deleted`', async () => {
    serve()
    post.mockResolvedValueOnce(ok({ ...DATA, templates: [CANAL] }, 'ok_set', 'Setări salvate'))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    open()
    await screen.findByLabelText('Nume')
    /* правка соседа не должна пропасть от удаления */
    fireEvent.click(item(/Tratament de canal/))
    fireEvent.change(screen.getByLabelText(/^Notă/), { target: { value: 'molari' } })
    fireEvent.click(item(/Implant \+ coroană/))
    fireEvent.click(btn(/Șterge șablonul/))
    expect(confirm.mock.calls[0]![0]).toMatch(/Ștergeți șablonul „Implant \+ coroană”\?/)
    expect(post).not.toHaveBeenCalled()
    fireEvent.click(btn(/Șterge șablonul/))
    await screen.findByText('Setări salvate')
    expect(post).toHaveBeenCalledWith('/settings/plan-templates', { deleted: ['pt1'] })
    expect(list().queryByRole('button', { name: /Implant \+ coroană/ })).toBeNull()
    expect(item(/Tratament de canal/).textContent).toMatch(/modificat/)
    expect((screen.getByLabelText(/^Notă/) as HTMLInputElement).value).toBe('molari')
  })

  it('несохранённый новый шаблон удаляется без запроса, но тоже после вопроса', async () => {
    serve()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    open()
    await screen.findByLabelText('Nume')
    fireEvent.click(btn(/Șablon nou/))
    fireEvent.change(nameInput(), { target: { value: 'Probă' } })
    fireEvent.click(btn(/Șterge șablonul/))
    await vi.waitFor(() => expect(list().queryByRole('button', { name: /Probă/ })).toBeNull())
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(post).not.toHaveBeenCalled()
    expect(saveBtn().disabled).toBe(true)
  })

  it('пустой каталог: слова и «Șablon nou»; отказ сервера — его текстом, правка остаётся', async () => {
    serve({ ...DATA, templates: [] })
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'dup_ptpl', text: 'Există deja un șablon', field: 'name' }, 'v'))
    open()
    expect(await screen.findByText(/Încă nu aveți șabloane de plan/)).toBeTruthy()
    expect(screen.getByText(/Alegeți un șablon din listă sau faceți unul nou/)).toBeTruthy()
    fireEvent.click(btn(/Șablon nou/))
    fireEvent.change(nameInput(), { target: { value: 'Igienizare completă' } })
    fireEvent.change(proc(1), { target: { value: 'consult' } })
    fireEvent.click(saveBtn())
    expect(await screen.findByText('Există deja un șablon')).toBeTruthy()
    expect(nameInput().value).toBe('Igienizare completă')
    expect(saveBtn().disabled).toBe(false)
  })
})
