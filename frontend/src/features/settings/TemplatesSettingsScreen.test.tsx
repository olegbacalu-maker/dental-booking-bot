import { cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { TemplatesData } from './settings'
import { openScreen } from '../../test/openScreen'
import { loadTemplatesSettings, TemplatesSettingsScreen } from './TemplatesSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

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
  max: 2000,
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
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
})

describe('TemplatesSettingsScreen', () => {
  it('услуги свёрнуты, состояние словом; метки — словами сервера; без правки сохранять нечего', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    open()
    expect(await screen.findByText('Consultație')).toBeTruthy()
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
    get.mockResolvedValueOnce(ok(DATA))
    const after: TemplatesData = { ...DATA, services: [DATA.services[0]!,
      { ...DATA.services[1]!, tpl: { ...DATA.services[1]!.tpl, tratament: 'Igienizare {data}' } }] }
    post.mockResolvedValueOnce(ok(after, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByText('Igienizare')
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
    get.mockResolvedValueOnce(ok(DATA))
    open()
    await screen.findByText('Consultație')
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

  it('стёртая графа уходит пустой строкой (стереть), отказ — текстом, правка остаётся', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_set', text: 'Setări invalide' }, 'v'))
    open()
    await screen.findByText('Igienizare')
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
