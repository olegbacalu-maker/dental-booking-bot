import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { RegistreSettingsScreen } from './RegistreSettingsScreen'
import type { Catalog } from './registre'

/* Setări › Registre sanitare (10.11): каталог по видам, редактор строки,
   «Lampă nouă» после вопроса, отказ сервера — его словами и полем. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const CAT: Catalog = {
  items: {
    ster: [{ id: 1, kind: 'ster', name: 'Melag 23 B+', nr: '23-11845', room: 'Sala de sterilizare', active: true,
      data: { type: 'abur', programs: [{ label: 'Universal 134 °C', temp: '134', pressure: '2,1', min: 5 }] } }],
    lamp: [{ id: 2, kind: 'lamp', name: 'OBN-150', nr: '2', room: 'Cabinet 1', active: true, used: 7962, rest: 38, low: true,
      data: { m3: 45, hours: 8000, base: 7000, since: '2025-03-01', screened: false, changes: [] } }],
    room: [{ id: 3, kind: 'room', name: 'Cabinet 1', nr: '', room: '', active: true, data: { every: 7 } }],
    solution: [], article: [{ id: 4, kind: 'article', name: 'Freze', nr: '', room: '', active: false, data: {} }], pack: [],
  },
  norms: { id: null, text: '' },
}

const card = (kind: string) => document.querySelector(`[data-kind="${kind}"]`) as HTMLElement

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); vi.restoreAllMocks() })

describe('RegistreSettingsScreen', () => {
  it('каталог по видам: программы автоклава, ресурс лампы, частота уборки, выключенная строка', async () => {
    get.mockResolvedValueOnce(ok(CAT))
    render(<RegistreSettingsScreen />)
    expect(await screen.findByText('Melag 23 B+')).toBeTruthy()
    expect(card('ster').textContent).toContain('Universal 134 °C · 2,1 bar · 5 min')
    expect(card('lamp').querySelector('.rg-item')?.className).toContain('low')
    expect(card('lamp').textContent).toContain('38 ore rămase din 8000')
    expect(card('room').textContent).toContain('la fiecare 7 zile')
    expect(card('article').querySelector('.rg-item')?.className).toContain('off')
  })

  it('новая лампа формой → тело с видом и данными; отказ — словами сервера', async () => {
    get.mockResolvedValue(ok(CAT))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_san', text: 'Completați câmpul marcat', field: 'hours' }, 'v'))
    post.mockResolvedValueOnce(ok({ id: 9 }, 'ok_san_item', 'Lista este salvată'))
    render(<RegistreSettingsScreen />)
    await screen.findByText('Melag 23 B+')
    fireEvent.click(within(card('lamp')).getByRole('button', { name: /Adaugă/ }))
    const ed = card('lamp').querySelector('.rg-edit') as HTMLElement
    const inputs = ed.querySelectorAll('input')
    fireEvent.change(inputs[0]!, { target: { value: 'Dezar-3' } })
    fireEvent.change(inputs[2]!, { target: { value: 'Cabinet 2' } })
    fireEvent.click(within(ed).getByRole('checkbox'))
    fireEvent.click(within(ed).getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText('Completați câmpul marcat')).toBeTruthy()
    expect((ed.querySelectorAll('input')[4] as HTMLInputElement).className).toContain('bad')
    fireEvent.click(within(ed).getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenLastCalledWith('/settings/registre/item', expect.objectContaining({
      kind: 'lamp', name: 'Dezar-3', room: 'Cabinet 2', data: expect.objectContaining({ hours: 8000, screened: true }) })))
    expect(await screen.findByText('Lista este salvată')).toBeTruthy()
  })

  it('«Lampă nouă» — после вопроса', async () => {
    get.mockResolvedValue(ok(CAT))
    post.mockResolvedValue(ok(null))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<RegistreSettingsScreen />)
    await screen.findByText('Melag 23 B+')
    fireEvent.click(within(card('lamp')).getByRole('button', { name: 'Lampă nouă' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(post).not.toHaveBeenCalled()
    fireEvent.click(within(card('lamp')).getByRole('button', { name: 'Lampă nouă' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/registre/lamp/2/new', {}))
  })
})
