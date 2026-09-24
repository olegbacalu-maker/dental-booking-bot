import { cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import type { CryptData } from './settings'
import { openScreen } from '../../test/openScreen'
import { CryptSettingsScreen, loadCryptSettings } from './CryptSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const SHEET = '/admin/settings/crypt/sheet'
const OFF: CryptData = {
  state: 'off',
  blocks: {
    status: '<div class="banner ok">Nu este obligatorie.</div>',
    what: '<p>Ce face.</p>',
    cost: '<p>Ce cere în schimb.</p>',
    limit: '<p>Ce NU face.</p>',
    note: '',
  },
  sheet: SHEET,
}
const ON: CryptData = {
  state: 'on',
  blocks: {
    status: '<div class="banner ok">Evidența este criptată.</div>',
    what: '', cost: '', limit: '',
    note: '<p>Copiile zilnice sunt și ele criptate.</p>',
  },
  sheet: SHEET,
}
const PENDING: CryptData = {
  state: 'pending',
  blocks: { status: '<div class="banner warn">Criptarea este pregătită.</div>',
            what: '', cost: '', limit: '', note: '' },
  sheet: SHEET,
}
const CLOUD: CryptData = {
  state: 'cloud',
  blocks: { status: '<p class="hint">Ediția cloud folosește PostgreSQL.</p>',
            what: '', cost: '', limit: '', note: '' },
  sheet: SHEET,
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/settings/crypt', '/admin/settings/crypt',
  <CryptSettingsScreen {...(navigate ? { navigate } : {})} />, loadCryptSettings, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('CryptSettingsScreen', () => {
  it('выключено: вся проза сервера и кнопка подготовки, листа ещё нет', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    open(vi.fn())
    expect(await screen.findByText('Nu este obligatorie.')).toBeTruthy()
    /* ⭐ Три абзаца «что даёт / чего стоит / чего НЕ делает» — решение Олега
       08-09: раздел не уговаривает, он называет цену. Потеряйся один из них
       на переносе, экран стал бы рекламой. */
    expect(screen.getByText('Ce face.')).toBeTruthy()
    expect(screen.getByText('Ce cere în schimb.')).toBeTruthy()
    expect(screen.getByText('Ce NU face.')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Pregătește criptarea/ })).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('подготовка уводит на печатный лист ПО АДРЕСУ СЕРВЕРА', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    post.mockResolvedValueOnce(ok({ sheet: SHEET }))
    const navigate = vi.fn()
    open(navigate)
    await screen.findByText('Nu este obligatorie.')
    fireEvent.click(screen.getByRole('button', { name: /Pregătește criptarea/ }))
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith(SHEET))
    expect(post).toHaveBeenCalledWith('/settings/crypt/prepare', {})
  })

  it('включено: лист, заметка про копии и остановка; отказ в подтверждении не шлёт ничего', async () => {
    get.mockResolvedValueOnce(ok(ON))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    open(vi.fn())
    expect(await screen.findByText('Evidența este criptată.')).toBeTruthy()
    expect(screen.getByText('Copiile zilnice sunt și ele criptate.')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Foaia de recuperare/ }).getAttribute('href')).toBe(SHEET)
    fireEvent.click(screen.getByRole('button', { name: 'Oprește criptarea' }))
    expect(post).not.toHaveBeenCalled()
  })

  it('остановка: подтверждение, POST и текст перезапуска с сервера', async () => {
    get.mockResolvedValueOnce(ok(ON))
    post.mockResolvedValueOnce(ok(
      { restart: true, text: 'Programul se închide acum și pornește din nou.',
        note: 'Datele clinicii nu sunt afectate.' }, 'ok_set', 'Setări salvate'))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    open(vi.fn())
    await screen.findByText('Evidența este criptată.')
    fireEvent.click(screen.getByRole('button', { name: 'Oprește criptarea' }))
    expect(await screen.findByText(/Programul se închide acum/)).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/crypt/off', {})
    /* Программа закрывается — предлагать что-то ещё нечестно. */
    expect(screen.queryByRole('button', { name: 'Oprește criptarea' })).toBeNull()
  })

  it('заказ сделан: только лист, ни одной кнопки действия', async () => {
    get.mockResolvedValueOnce(ok(PENDING))
    open(vi.fn())
    expect(await screen.findByText('Criptarea este pregătită.')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Deschide foaia de recuperare/ })).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('облако: объяснение без заголовка раздела — как на старой странице', async () => {
    get.mockResolvedValueOnce(ok(CLOUD))
    open(vi.fn())
    expect(await screen.findByText('Ediția cloud folosește PostgreSQL.')).toBeTruthy()
    expect(screen.queryByRole('heading')).toBeNull()
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
  })
})
