import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { LanData } from './settings'
import { LanSettingsScreen } from './LanSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const OFF: LanData = {
  enabled: false, ip: '', port: 8088, url: '', firewall: null,
  blocks: { intro: '<p>Un program, o singură evidență.</p>', status: '<p>Accesul este oprit</p>', firewall: '', tips: '' },
}
const ON: LanData = {
  enabled: true, ip: '192.168.1.5', port: 8088, url: 'http://192.168.1.5:8088/admin', firewall: false,
  blocks: {
    intro: OFF.blocks.intro,
    status: '<p>Activ. http://192.168.1.5:8088/admin</p>',
    firewall: '<p>Regula de firewall lipsește</p>',
    tips: '<p>De știut</p>',
  },
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('LanSettingsScreen', () => {
  it('выключено: проза сервера и кнопка включения', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    render(<LanSettingsScreen />)
    expect(await screen.findByText('Un program, o singură evidență.')).toBeTruthy()
    expect(screen.getByText('Accesul este oprit')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Activează accesul' })).toBeTruthy()
    expect(screen.queryByText('De știut')).toBeNull()
  })

  it('включение: подтверждение, POST mode=on, текст перезапуска с сервера', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    post.mockResolvedValueOnce(ok({ enabled: true, restart: true,
      text: 'Programul se închide acum și pornește din nou — setarea se aplică la pornire.',
      note: 'Datele clinicii nu sunt afectate.' }, 'ok_set', 'Setări salvate'))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    render(<LanSettingsScreen />)
    await screen.findByText('Accesul este oprit')
    fireEvent.click(screen.getByRole('button', { name: 'Activează accesul' }))
    expect(await screen.findByText(/Programul se închide acum/)).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/lan', { mode: 'on' })
    expect(screen.queryByRole('button', { name: 'Activează accesul' })).toBeNull()
  })

  it('отказ в подтверждении — ничего не шлёт', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    render(<LanSettingsScreen />)
    await screen.findByText('Accesul este oprit')
    fireEvent.click(screen.getByRole('button', { name: 'Activează accesul' }))
    expect(post).not.toHaveBeenCalled()
  })

  it('вне настольного издания текста нет: плашка и перечитывание', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    post.mockResolvedValueOnce(ok({ enabled: true, restart: false, text: '', note: '' }, 'ok_set', 'Setări salvate'))
    get.mockResolvedValueOnce(ok(ON))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    render(<LanSettingsScreen />)
    await screen.findByText('Accesul este oprit')
    fireEvent.click(screen.getByRole('button', { name: 'Activează accesul' }))
    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    expect(await screen.findByRole('button', { name: 'Dezactivează accesul' })).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('включено без правила брандмауэра: блок, кнопка, повторное чтение после запроса', async () => {
    get.mockResolvedValueOnce(ok(ON))
    post.mockResolvedValueOnce(ok({ asked: true }))
    get.mockResolvedValueOnce(ok({ ...ON, firewall: true, blocks: { ...ON.blocks, firewall: '' } }))
    render(<LanSettingsScreen />)
    expect(await screen.findByText('Regula de firewall lipsește')).toBeTruthy()
    expect(screen.getByText('De știut')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Creează regula de firewall/ }))
    await waitFor(() => expect(screen.queryByText('Regula de firewall lipsește')).toBeNull())
    expect(post).toHaveBeenCalledWith('/settings/lan/firewall', {})
  })

  it('секции нет в этом издании (404) — своя фраза', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 'nf'))
    render(<LanSettingsScreen />)
    expect(await screen.findByText(/doar în ediția instalată/)).toBeTruthy()
  })
})
