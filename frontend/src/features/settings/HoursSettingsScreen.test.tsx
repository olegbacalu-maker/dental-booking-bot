import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { HoursData } from './settings'
import { HoursSettingsScreen } from './HoursSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const HOURS: HoursData = {
  hours: { mon: [9, 18], tue: [9, 18, 13, 14], wed: null },
  range: { min: 7, max: 21 },
  days: [{ key: 'mon', label: 'Luni' }, { key: 'tue', label: 'Marți' }, { key: 'wed', label: 'Miercuri' }],
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const sel = (label: string) => screen.getByLabelText(label) as HTMLSelectElement

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('HoursSettingsScreen', () => {
  it('строки дней: закрытый день, обед, диапазон часов с сервера', async () => {
    get.mockResolvedValueOnce(ok(HOURS))
    render(<HoursSettingsScreen />)
    expect(await screen.findByText('Luni')).toBeTruthy()
    expect(sel('Luni: De la').value).toBe('9')
    expect(sel('Luni: Pauză de la').value).toBe('')
    expect(sel('Marți: Pauză de la').value).toBe('13')
    expect(sel('Marți: Pauză până la').value).toBe('14')
    const closed = screen.getAllByRole('checkbox')[2] as HTMLInputElement
    expect(closed.checked).toBe(true)
    expect(sel('Miercuri: De la').disabled).toBe(true)
    expect(sel('Luni: De la').options[0]?.value).toBe('7')
    expect(sel('Luni: Până la').options[0]?.value).toBe('8')
    expect(sel('Luni: De la').options.length).toBe(15)
  })

  it('сохранение: тот же payload, что у старой страницы; ответ подменяет таблицу', async () => {
    get.mockResolvedValueOnce(ok(HOURS))
    post.mockResolvedValueOnce(ok({ ...HOURS, hours: { mon: [10, 18, 13, 14], tue: [9, 18], wed: [8, 12] } }, 'ok_set', 'Setări salvate'))
    render(<HoursSettingsScreen />)
    await screen.findByText('Luni')
    fireEvent.change(sel('Luni: De la'), { target: { value: '10' } })
    fireEvent.change(sel('Luni: Pauză de la'), { target: { value: '13' } })
    fireEvent.change(sel('Luni: Pauză până la'), { target: { value: '14' } })
    fireEvent.change(sel('Marți: Pauză de la'), { target: { value: '' } })
    fireEvent.click(screen.getAllByRole('checkbox')[2] as HTMLInputElement)
    fireEvent.change(sel('Miercuri: De la'), { target: { value: '8' } })
    fireEvent.change(sel('Miercuri: Până la'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează programul/ }))
    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/hours', {
      hours: { mon: [10, 18, 13, 14], tue: [9, 18], wed: [8, 12] },
    })
    expect(sel('Marți: Pauză de la').value).toBe('')
    expect(sel('Miercuri: De la').value).toBe('8')
  })

  it('отказ проверки — текст сервера, таблица остаётся', async () => {
    get.mockResolvedValueOnce(ok(HOURS))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_set', text: 'Setări invalide' }, 'v'))
    render(<HoursSettingsScreen />)
    await screen.findByText('Luni')
    fireEvent.click(screen.getByRole('button', { name: /Salvează programul/ }))
    expect(await screen.findByText('Setări invalide')).toBeTruthy()
    expect(sel('Luni: De la').value).toBe('9')
  })
})
