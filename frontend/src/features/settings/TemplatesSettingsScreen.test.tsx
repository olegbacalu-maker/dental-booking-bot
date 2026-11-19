import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { screenRoute } from '../../hooks/useRouteLoad'
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
/* Мост к оболочке: что заявил экран (`useCommand`) и стоит ли окно оболочки;
   перезагрузка — записью, jsdom документ не меняет. */
const { claims, shell, reload } = vi.hoisted(() => ({
  claims: new Map<string, () => void>(), shell: { on: false }, reload: vi.fn(),
}))
vi.mock('../../app/bridge', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../app/bridge')>(),
  shellOn: () => shell.on,
  useCommand: (id: string, run: (() => void) | null | false | undefined) => {
    if (run) claims.set(id, run)
    else claims.delete(id)
  },
}))
vi.mock('../../hooks/useLive', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../hooks/useLive')>(),
  defaultReload: reload,
}))

const E = { acuze: '', examen: '', diagnostic: '', tratament: '', recomandari: '' }
const DATA: TemplatesData = {
  services: [
    { id: 'consult', label: 'Consultație', tpl: { ...E } },
    { id: 'hygiene', label: 'Igienizare', tpl: { ...E, diagnostic: 'Depozite {dinte}', recomandari: 'Control' } },
  ],
  fields: [
    { id: 'acuze', label: 'Acuze / motivul prezentării', rows: 2 },
    { id: 'examen', label: 'Examen obiectiv', rows: 3 },
    { id: 'diagnostic', label: 'Diagnostic', rows: 2 },
    { id: 'tratament', label: 'Tratament efectuat', rows: 3 },
    { id: 'recomandari', label: 'Recomandări', rows: 2 },
  ],
  marks: { tooth: '{dinte}', date: '{data}' },
  example: { ...E, diagnostic: 'Exemplu, editați: diagnosticul, dintele {dinte}.',
    recomandari: 'Exemplu, editați: recomandările.' },
  general: [
    { id: 'obturatie', label: 'Obturație', values: { ...E, diagnostic: 'Carie dentară, dintele {dinte}.', tratament: 'Obturație.' } },
    { id: 'control', label: 'Control', values: { ...E, acuze: 'Prezentare la control programat.' } },
  ],
  max: 2000,
}

const PLAN: PlanTemplatesData = {
  templates: [], services: [], created: [],
  max: { name: 60, note: 120, rows: 40, price: 1000000, templates: 100 },
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
/* экран грузит обе вкладки разом: ответ — по адресу запроса */
const serve = (consult: TemplatesData = DATA) => get.mockImplementation((path: string) =>
  Promise.resolve(ok(path === '/settings/templates' ? consult : PLAN)))
const svc = (label: RegExp) => screen.findByRole('button', { name: label })
const area = (id: string) => document.getElementById(id) as HTMLTextAreaElement
const head = (label: RegExp) => screen.getByRole('button', { name: label })
const saveBtn = () => screen.getByRole('button', { name: /Salvează șabloanele/ }) as HTMLButtonElement

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/settings/templates', '/admin/settings/templates',
  <TemplatesSettingsScreen {...(navigate ? { navigate } : {})} />, loadTemplatesSettings, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  claims.clear()
  shell.on = false
  reload.mockReset()
  vi.restoreAllMocks()
})

describe('TemplatesSettingsScreen — вкладка «Consultație»', () => {
  it('две вкладки одного экрана: «Consultație» открыта, «Plan de tratament» — по щелчку и в адресе', async () => {
    serve()
    const { router } = open()
    await svc(/Consultație/)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => [t.textContent, t.getAttribute('aria-selected')]))
      .toEqual([['Consultație', 'true'], ['Plan de tratament', 'false']])
    expect(get.mock.calls.map((c) => c[0]).sort()).toEqual(['/settings/plan-templates', '/settings/templates'])
    fireEvent.click(tabs[1]!)
    expect(await screen.findByText(/Încă nu aveți șabloane de plan/)).toBeTruthy()
    expect(router.state.location.search).toBe('?tab=plan')
    expect(screen.queryByRole('button', { name: /Igienizare/ })).toBeNull()
    /* смена вкладки данные не перечитывает */
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('правка в одной вкладке переживает взгляд в другую и метит вкладку', async () => {
    serve()
    open()
    fireEvent.click(await svc(/Igienizare/))
    fireEvent.change(area('tpl_hygiene_tratament'), { target: { value: 'Igienizare {data}' } })
    const [consult, plan] = screen.getAllByRole('tab')
    expect(consult!.querySelector('.tpl-dirty')).not.toBeNull()
    fireEvent.click(plan!)
    await screen.findByText(/Încă nu aveți șabloane de plan/)
    fireEvent.click(consult!)
    expect(area('tpl_hygiene_tratament').value).toBe('Igienizare {data}')
    expect(saveBtn().disabled).toBe(false)
  })

  it('услуги свёрнуты, состояние словом; метки — словами сервера; без правки сохранять нечего', async () => {
    serve()
    open()
    expect(await svc(/Consultație/)).toBeTruthy()
    expect(head(/Consultație/).getAttribute('aria-expanded')).toBe('false')
    expect(head(/Consultație/).textContent).toMatch(/gol/)
    expect(head(/Igienizare/).textContent).toMatch(/2 câmpuri completate/)
    expect(screen.getByText('{dinte}')).toBeTruthy()
    expect(screen.getByText('{data}')).toBeTruthy()
    expect(document.querySelector('textarea')).toBeNull()
    expect(saveBtn().disabled).toBe(true)
    expect(document.body.textContent).not.toMatch(/protocol/i)
  })

  it('⭐ на запись уходит только ТРОНУТОЕ: графа, а не вся услуга; соседняя услуга — никак', async () => {
    serve()
    const after: TemplatesData = { ...DATA, services: [DATA.services[0]!,
      { ...DATA.services[1]!, tpl: { ...DATA.services[1]!.tpl, tratament: 'Igienizare {data}' } }] }
    post.mockResolvedValueOnce(ok(after, 'ok_set', 'Setări salvate'))
    open()
    await svc(/Igienizare/)
    fireEvent.click(head(/Igienizare/))
    expect(area('tpl_hygiene_diagnostic').value).toBe('Depozite {dinte}')
    fireEvent.change(area('tpl_hygiene_tratament'), { target: { value: 'Igienizare {data}' } })
    expect(head(/Igienizare/).textContent).toMatch(/3 câmpuri completate · modificat/)
    fireEvent.click(saveBtn())
    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/templates',
      { templates: { hygiene: { tratament: 'Igienizare {data}' } } })
    expect(head(/Igienizare/).textContent).not.toMatch(/modificat/)
    expect(saveBtn().disabled).toBe(true)
  })

  it('пустой шаблон: «Exemplu» кладёт заглушку сервера в пустые графы; у заполненного кнопки нет', async () => {
    serve()
    open()
    await svc(/Consultație/)
    fireEvent.click(head(/Consultație/))
    fireEvent.click(head(/Igienizare/))
    expect(screen.getAllByRole('button', { name: 'Exemplu' }).length).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Exemplu' }))
    expect(area('tpl_consult_diagnostic').value).toBe('Exemplu, editați: diagnosticul, dintele {dinte}.')
    expect(area('tpl_consult_acuze').value).toBe('')
    expect(screen.queryByRole('button', { name: 'Exemplu' })).toBeNull()
    fireEvent.click(saveBtn())
    expect(post).toHaveBeenCalledWith('/settings/templates', { templates: { consult: {
      diagnostic: 'Exemplu, editați: diagnosticul, dintele {dinte}.',
      recomandari: 'Exemplu, editați: recomandările.' } } })
  })

  it('10.11: «Copiază din șablon general» — текст общей заготовки в пустые графы; у заполненной услуги выбора нет', async () => {
    serve()
    open()
    await svc(/Consultație/)
    fireEvent.click(head(/Consultație/))
    fireEvent.click(head(/Igienizare/))
    const pick = screen.getByLabelText('Copiază din șablon general: Consultație') as HTMLSelectElement
    expect(screen.queryByLabelText('Copiază din șablon general: Igienizare')).toBeNull()
    expect(Array.from(pick.options).map((o) => o.textContent)).toEqual(['Copiază din șablon general…', 'Obturație', 'Control'])
    fireEvent.change(pick, { target: { value: 'obturatie' } })
    expect(area('tpl_consult_diagnostic').value).toBe('Carie dentară, dintele {dinte}.')
    expect(area('tpl_consult_tratament').value).toBe('Obturație.')
    expect(area('tpl_consult_acuze').value).toBe('')
    expect(screen.queryByLabelText('Copiază din șablon general: Consultație')).toBeNull()
    fireEvent.click(saveBtn())
    expect(post).toHaveBeenCalledWith('/settings/templates', { templates: { consult: {
      diagnostic: 'Carie dentară, dintele {dinte}.', tratament: 'Obturație.' } } })
  })

  it('стёртая графа уходит пустой строкой (стереть), отказ — текстом, правка остаётся', async () => {
    serve()
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_set', text: 'Setări invalide' }, 'v'))
    open()
    await svc(/Igienizare/)
    fireEvent.click(head(/Igienizare/))
    fireEvent.change(area('tpl_hygiene_recomandari'), { target: { value: '' } })
    fireEvent.click(saveBtn())
    expect(await screen.findByText('Setări invalide')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/templates', { templates: { hygiene: { recomandari: '' } } })
    expect(area('tpl_hygiene_recomandari').value).toBe('')
    expect(saveBtn().disabled).toBe(false)
  })

  it('401 при первой загрузке — уход на вход', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open(navigate)
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})

/* Несохранённая правка шаблонов при уходе с экрана: до этого о ней говорили
   только точка на вкладке и «modificat» в списке, и набранное пропадало молча.
   Блокер — у экрана (владельца обеих вкладок), окно — `ask`; F5 и закрытие —
   `useUnsavedPage`, как в фише. */
describe('TemplatesSettingsScreen — вопрос при уходе с несохранённой правкой', () => {
  const Q = 'Părăsiți ecranul fără să le salvați?'
  const CONSULT_Q = 'Șabloanele de consultație au modificări nesalvate.'
  const PLAN_Q = 'Șabloanele de plan au modificări nesalvate.'
  /* экран и хаб настроек рядом — чтобы было куда уйти роутером */
  const show = async () => {
    serve()
    const router = createMemoryRouter([
      screenRoute('/admin/settings/templates', <TemplatesSettingsScreen />, loadTemplatesSettings),
      { path: '/admin/settings', element: <p>Hub setări</p> },
    ], { initialEntries: ['/admin/settings/templates'] })
    render(<RouterProvider router={router} />)
    await svc(/Igienizare/)
    return router
  }
  const editConsult = () => {
    fireEvent.click(head(/Igienizare/))
    fireEvent.change(area('tpl_hygiene_tratament'), { target: { value: 'Igienizare {data}' } })
  }
  const unload = () => {
    const e = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(e)
    return e.defaultPrevented
  }

  it('без правки — уход без вопроса; смена вкладки с правкой вопроса не задаёт', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const router = await show()
    editConsult()
    fireEvent.click(screen.getAllByRole('tab')[1]!)
    await screen.findByText(/Încă nu aveți șabloane de plan/)
    expect(router.state.location.search).toBe('?tab=plan')
    expect(confirm).not.toHaveBeenCalled()
    cleanup()
    const clean = await show()
    await act(() => clean.navigate('/admin/settings'))
    expect(await screen.findByText('Hub setări')).toBeTruthy()
    expect(confirm).not.toHaveBeenCalled()
  })

  it('уход на другой экран с правкой: вопрос называет вкладку; отказ оставляет экран и ввод, согласие уводит', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const router = await show()
    editConsult()
    act(() => { void router.navigate('/admin/settings') })
    await waitFor(() => expect(confirm).toHaveBeenLastCalledWith(`${CONSULT_Q} ${Q}`))
    expect(router.state.location.pathname).toBe('/admin/settings/templates')
    expect(area('tpl_hygiene_tratament').value).toBe('Igienizare {data}')
    /* правка и во второй вкладке — вопрос называет обе */
    fireEvent.click(screen.getAllByRole('tab')[1]!)
    fireEvent.click(await screen.findByRole('button', { name: /Șablon nou/ }))
    act(() => { void router.navigate('/admin/settings') })
    await waitFor(() => expect(confirm).toHaveBeenLastCalledWith(`${CONSULT_Q} ${PLAN_Q} ${Q}`))
    expect(router.state.location.pathname).toBe('/admin/settings/templates')
    confirm.mockReturnValue(true)
    act(() => { void router.navigate('/admin/settings') })
    expect(await screen.findByText('Hub setări')).toBeTruthy()
  })

  it('после записи спрашивать не о чем', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const after: TemplatesData = { ...DATA, services: [DATA.services[0]!,
      { ...DATA.services[1]!, tpl: { ...DATA.services[1]!.tpl, tratament: 'Igienizare {data}' } }] }
    post.mockResolvedValueOnce(ok(after, 'ok_set', 'Setări salvate'))
    const router = await show()
    editConsult()
    fireEvent.click(saveBtn())
    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    await act(() => router.navigate('/admin/settings'))
    expect(await screen.findByText('Hub setări')).toBeTruthy()
    expect(confirm).not.toHaveBeenCalled()
  })

  it('без оболочки — beforeunload только с правкой; в окне оболочки «Reîncarcă» спрашивает своим окном', async () => {
    await show()
    expect(unload()).toBe(false)
    expect(claims.has('act:reload')).toBe(false)
    editConsult()
    expect(unload()).toBe(true)
    cleanup()
    shell.on = true
    await show()
    editConsult()
    expect(unload()).toBe(false)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    act(() => claims.get('act:reload')!())
    await waitFor(() => expect(confirm).toHaveBeenLastCalledWith(
      `${CONSULT_Q} Reîncărcați pagina fără să le salvați?`))
    expect(reload).not.toHaveBeenCalled()
    confirm.mockReturnValueOnce(true)
    act(() => claims.get('act:reload')!())
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
  })
})
