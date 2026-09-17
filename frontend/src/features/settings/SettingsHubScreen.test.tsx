import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { HubData } from './settings'
import { SettingsHubScreen } from './SettingsHubScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const HUB: HubData = {
  tiles: [
    { href: '/admin/settings/system', icon: 'info', tone: 'b', label: 'Stare sistem',
      hint: [{ t: 'v1.26.0 · ' }, { icon: 'refresh', t: 'disponibilă 1.27.0', tone: 'amber' }] },
    { href: '/admin/settings/clinic', icon: 'clinic', tone: 'g', label: 'Clinica', hint: [{ t: 'Clinica Test' }] },
    { href: '/admin/settings/theme', icon: 'palette', tone: 'v', label: 'Aspectul clinicii',
      hint: [{ t: 'Modern · ' }, { dot: '#0E9F8A' }, { t: '#0E9F8A' }] },
    { href: '/admin/settings/faq', icon: 'nope', tone: 'v', label: 'Întrebări frecvente', hint: [{ t: 'copii' }] },
  ],
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })

afterEach(() => {
  cleanup()
  get.mockReset()
})

describe('SettingsHubScreen', () => {
  it('плитки: ссылки, подписи, куски состояния (иконка с тоном, точка цвета)', async () => {
    get.mockResolvedValueOnce(ok(HUB))
    render(<SettingsHubScreen />)
    expect(await screen.findByText('Stare sistem')).toBeTruthy()
    const tiles = document.querySelectorAll('a.pl-tile')
    expect(tiles.length).toBe(4)
    expect(tiles[0]?.getAttribute('href')).toBe('/admin/settings/system')
    expect(tiles[0]?.querySelector('.ico')?.className).toBe('ico b')
    const amber = screen.getByText(/disponibilă 1.27.0/)
    expect(amber.tagName).toBe('B')
    expect(amber.className).toBe('dp-tone-amber')
    expect(amber.querySelector('svg')).toBeTruthy()
    expect((document.querySelector('.th-dot') as HTMLElement).style.background).toBe('rgb(14, 159, 138)')
    expect(screen.getByText('Clinica Test')).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/settings/hub', expect.anything())
  })

  it('неизвестная иконка с сервера не роняет экран', async () => {
    get.mockResolvedValueOnce(ok(HUB))
    render(<SettingsHubScreen />)
    expect(await screen.findByText('Întrebări frecvente')).toBeTruthy()
    // у каждой плитки свой значок; «nope» с сервера стал общим, а не пустотой
    expect(document.querySelectorAll('a.pl-tile .ico svg').length).toBe(4)
  })

  it('загрузка и отказ', async () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    const { unmount } = render(<SettingsHubScreen />)
    expect(document.querySelector('section')?.getAttribute('aria-busy')).toBe('true')
    unmount()
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    render(<SettingsHubScreen />)
    expect(await screen.findByRole('button', { name: /Reîncearcă/ })).toBeTruthy()
  })
})
