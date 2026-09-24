import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import type { ThemeData } from './settings'
import { loadThemeSettings, ThemeSettingsScreen } from './ThemeSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const THEME: ThemeData = {
  style: 'modern', primary: '#0E9F8A', custom: false,
  styles: [
    { key: 'modern', label: 'Modern', hint: 'implicit', vars: { '--r-card': '14px', '--bg': '#fff', '--line': '#ddd', '--sh': 'none', '--r-ctl': '8px' } },
    { key: 'calm', label: 'Calm', hint: 'moale', vars: { '--r-card': '20px', '--bg': '#f7f7f7', '--line': '#eee', '--sh': 'none', '--r-ctl': '12px' } },
  ],
  presets: [{ hex: '#0E9F8A', name: 'Verde DentPilot' }, { hex: '#7C3AED', name: 'Violet' }],
  palettes: {
    modern: { '#0E9F8A': { '--teal': '#0E9F8A' }, '#7C3AED': { '--teal': '#7C3AED' } },
    calm: { '#0E9F8A': { '--teal': '#0E9F8A' }, '#7C3AED': { '--teal': '#7C3AED' } },
  },
  logo: null, logo_topbar: false, logo_max_mb: 2,
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const teal = () => document.documentElement.style.getPropertyValue('--teal')

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/settings/theme', '/admin/settings/theme',
  <ThemeSettingsScreen {...(navigate ? { navigate } : {})} />, loadThemeSettings, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  postForm.mockReset()
  document.documentElement.removeAttribute('style')
})

describe('ThemeSettingsScreen', () => {
  it('стили и цвета из ответа, текущий выбор отмечен, без логотипа', async () => {
    get.mockResolvedValueOnce(ok(THEME))
    open()
    expect(await screen.findByText('Modern')).toBeTruthy()
    expect((screen.getByDisplayValue('modern') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByDisplayValue('#0E9F8A') as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText('fără logo')).toBeTruthy()
    expect(screen.queryByLabelText(/bara de sus/)).toBeNull()
  })

  it('выбор цвета из набора красит страницу палитрой сервера, без запроса', async () => {
    get.mockResolvedValueOnce(ok(THEME))
    open()
    await screen.findByText('Modern')
    fireEvent.click(screen.getByDisplayValue('#7C3AED'))
    expect(teal()).toBe('#7C3AED')
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('свой цвет: палитру считает сервер', async () => {
    get.mockResolvedValueOnce(ok(THEME))
    get.mockResolvedValueOnce(ok({ '--teal': '#123456' }))
    open()
    await screen.findByText('Modern')
    fireEvent.change(screen.getByLabelText('Culoare personalizată'), { target: { value: '#123456' } })
    await waitFor(() => expect(teal()).toBe('#123456'))
    expect(get).toHaveBeenLastCalledWith('/settings/theme/palette?c=%23123456&style=modern')
  })

  it('сохранение шлёт те же поля, что форма', async () => {
    get.mockResolvedValueOnce(ok(THEME))
    post.mockResolvedValueOnce(ok({ ...THEME, style: 'calm', primary: '#7C3AED' }, 'ok_theme', 'Aspectul clinicii a fost salvat'))
    open()
    await screen.findByText('Modern')
    fireEvent.click(screen.getByDisplayValue('calm'))
    fireEvent.click(screen.getByDisplayValue('#7C3AED'))
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    expect(await screen.findByText('Aspectul clinicii a fost salvat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/theme', { style: 'calm', primary: '#7C3AED', custom: '#0E9F8A', logo_topbar: false })
  })

  it('логотип: загрузка multipart, галочка шапки, удаление', async () => {
    get.mockResolvedValueOnce(ok(THEME))
    postForm.mockResolvedValueOnce(ok({ ...THEME, logo: '/clinic-logo?v=1' }, 'ok_logo', 'Logo salvat'))
    post.mockResolvedValueOnce(ok({ ...THEME, logo: '/clinic-logo?v=1', logo_topbar: true }, 'ok_theme', 'Aspectul salvat'))
    post.mockResolvedValueOnce(ok(THEME, 'no_logo', 'Logo șters'))
    open()
    await screen.findByText('Modern')
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'logo.png', { type: 'image/png' })
    fireEvent.change(document.getElementById('thlogo') as HTMLInputElement, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Încarcă' }))
    expect(await screen.findByText('Logo salvat')).toBeTruthy()
    expect((postForm.mock.calls[0] as [string, FormData])[0]).toBe('/settings/theme/logo')
    expect(document.querySelector('img.th-logo')?.getAttribute('src')).toBe('/clinic-logo?v=1')
    fireEvent.click(screen.getByLabelText(/bara de sus/))
    expect(await screen.findByText('Aspectul salvat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/theme', { style: 'modern', primary: '#0E9F8A', custom: '#0E9F8A', logo_topbar: true })
    fireEvent.click(screen.getByRole('button', { name: /Șterge/ }))
    expect(await screen.findByText('Logo șters')).toBeTruthy()
    expect(post).toHaveBeenLastCalledWith('/settings/theme/logo/delete', {})
    expect(screen.getByText('fără logo')).toBeTruthy()
  })
})
