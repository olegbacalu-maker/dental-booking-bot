import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { ServicesData } from './settings'
import { ServicesSettingsScreen } from './ServicesSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const DATA: ServicesData = {
  services: [
    { id: 'consult', ro: 'Consultație', ru: 'Консультация', price: 'gratuit', duration: 60, color: '', urgent: false, docs: [] },
    { id: 'pain', ro: 'Durere acută', ru: 'Острая боль', price: '', duration: 60, color: 'red', urgent: true, docs: ['d2'] },
  ],
  palette: { green: 'verde', red: 'roșu' },
  durations: [15, 30, 45, 60, 90, 120],
  doctors: [{ id: 'd2', name: 'Dr. Doi' }, { id: 'd3', name: 'Dr. Trei' }],
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('ServicesSettingsScreen', () => {
  it('строки: цена, длительность, цвет, срочность, врачи галочками', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    render(<ServicesSettingsScreen />)
    expect(await screen.findByDisplayValue('Consultație')).toBeTruthy()
    expect(input('Preț 1').value).toBe('gratuit')
    expect((screen.getByLabelText('Durată 2') as HTMLSelectElement).value).toBe('60')
    expect((screen.getByLabelText('Culoare 2') as HTMLSelectElement).value).toBe('red')
    expect(input('urgent 2').checked).toBe(true)
    expect(input('urgent 1').checked).toBe(false)
    expect(screen.getAllByText('gol = toți').length).toBe(1)
    const rows = document.querySelectorAll('tbody tr')
    expect(rows.length).toBe(2)
    const docs2 = rows[1]?.querySelectorAll('.dp-svc-docs input') as NodeListOf<HTMLInputElement>
    expect(docs2[0]?.checked).toBe(true)
    expect(docs2[1]?.checked).toBe(false)
  })

  it('добавить, поправить, удалить, сохранить: тело запроса как у старой таблицы', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockResolvedValueOnce(ok({ ...DATA, services: [DATA.services[1]!, { id: 's1', ro: 'Albire', ru: 'Albire', price: '1500 MDL', duration: 90, color: 'green', urgent: false, docs: ['d3'] }] }, 'ok_set', 'Setări salvate'))
    render(<ServicesSettingsScreen />)
    await screen.findByDisplayValue('Consultație')
    fireEvent.click(screen.getByRole('button', { name: '+ Adaugă serviciu' }))
    fireEvent.change(input('Denumire (RO) 3'), { target: { value: 'Albire' } })
    fireEvent.change(input('Preț 3'), { target: { value: '1500 MDL' } })
    fireEvent.change(screen.getByLabelText('Durată 3'), { target: { value: '90' } })
    fireEvent.change(screen.getByLabelText('Culoare 3'), { target: { value: 'green' } })
    const docs3 = document.querySelectorAll('tbody tr')[2]?.querySelectorAll('.dp-svc-docs input') as NodeListOf<HTMLInputElement>
    fireEvent.click(docs3[1] as HTMLInputElement)
    fireEvent.click(screen.getByRole('button', { name: 'Șterge rândul 1' }))
    fireEvent.click(screen.getByRole('button', { name: /Salvează serviciile/ }))
    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/services', { services: [
      DATA.services[1],
      { id: '', ro: 'Albire', ru: '', price: '1500 MDL', duration: 90, color: 'green', urgent: false, docs: ['d3'] },
    ] })
    expect(input('Denumire (RO) 2').value).toBe('Albire')
    expect(screen.queryByDisplayValue('Consultație')).toBeNull()
  })

  it('отказ сервера — текст в плашке, правки остаются', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_set', text: 'Setări invalide' }, 'v'))
    render(<ServicesSettingsScreen />)
    await screen.findByDisplayValue('Consultație')
    fireEvent.change(input('Denumire (RO) 1'), { target: { value: 'Durere acută' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează serviciile/ }))
    expect(await screen.findByText('Setări invalide')).toBeTruthy()
    expect(input('Denumire (RO) 1').value).toBe('Durere acută')
  })
})
