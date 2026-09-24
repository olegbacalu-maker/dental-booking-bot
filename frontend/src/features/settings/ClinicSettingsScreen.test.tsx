import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { ClinicSettings } from './clinicSettings'
import { openScreen } from '../../test/openScreen'
import { ClinicSettingsScreen, loadClinicSettings } from './ClinicSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26): экран получает то, что
   отдал бы движок, а бандл этого файла не видит. */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../services/api')>(),
  api: { get, post },
  loginUrl: () => '/admin/login?next=%2Fadmin%2Fsettings%2Fclinic',
}))

const SAMPLE: ClinicSettings = {
  name: 'Clinica Test',
  phone: '+373 60 000 000',
  address: { ro: 'str. Test 1, Cahul', ru: '' },
  template: false,
  hint: 'Programul încă are datele de exemplu.',
}

function ok<T>(data: T, code = '', text = ''): ApiResult<T> {
  return { data, code, text, tone: 'ok' }
}

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement

/* Экран грузит роутер (B2): открывается тем же маршрутом, что в App.tsx. */
const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/settings/clinic', '/admin/settings/clinic',
  <ClinicSettingsScreen {...(navigate ? { navigate } : {})} />, loadClinicSettings, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('ClinicSettingsScreen', () => {
  it('загрузка: форма видна, но занята и пуста', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    open()
    expect(screen.getByRole('heading').textContent).toContain('Clinica')
    expect(document.querySelector('section')?.getAttribute('aria-busy')).toBe('true')
    expect(input('Nume').disabled).toBe(true)
    expect(screen.getByRole('button', { name: /Salvează/ })).toHaveProperty('disabled', true)
  })

  it('успех: поля заполнены данными движка, форма отпущена', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    open()
    expect(await screen.findByDisplayValue('Clinica Test')).toBeTruthy()
    expect(input('Telefon').value).toBe('+373 60 000 000')
    expect(input('Adresa (RO)').value).toBe('str. Test 1, Cahul')
    expect(input('Adresa (RU)').value).toBe('')
    expect(input('Nume').disabled).toBe(false)
    expect(document.querySelector('section')?.getAttribute('aria-busy')).toBe('false')
    expect(get).toHaveBeenCalledWith('/settings/clinic', expect.anything())
  })

  it('пустое состояние: шаблонный профиль показывает подсказку сервера', async () => {
    get.mockResolvedValueOnce(ok({ ...SAMPLE, template: true }))
    open()
    expect(await screen.findByText('Programul încă are datele de exemplu.')).toBeTruthy()
  })

  it('обычный профиль подсказку не показывает', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    open()
    await screen.findByDisplayValue('Clinica Test')
    expect(screen.queryByText('Programul încă are datele de exemplu.')).toBeNull()
  })

  it('сохранение: шлёт форму, показывает текст сервера, берёт данные из ответа', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    post.mockResolvedValueOnce(ok({ ...SAMPLE, name: 'Clinica Nouă' }, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByDisplayValue('Clinica Test')

    /* Набрано с пробелами, сервер вернул обрезанное: поле обязано показать
       ОТВЕТ, иначе «берёт данные из ответа» ничего бы не доказывало. */
    fireEvent.change(input('Nume'), { target: { value: '  Clinica Nouă  ' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))

    expect(await screen.findByText('Setări salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/clinic', {
      name: '  Clinica Nouă  ',
      phone: '+373 60 000 000',
      address: { ro: 'str. Test 1, Cahul', ru: '' },
    })
    expect(input('Nume').value).toBe('Clinica Nouă')
    expect(screen.getByRole('status').getAttribute('data-kind')).toBe('ok')
  })

  it('плашка закрывается крестиком', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    post.mockResolvedValueOnce(ok(SAMPLE, 'ok_set', 'Setări salvate'))
    open()
    await screen.findByDisplayValue('Clinica Test')
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await screen.findByText('Setări salvate')
    fireEvent.click(screen.getByRole('button', { name: 'Închide' }))
    await waitFor(() => expect(screen.queryByText('Setări salvate')).toBeNull())
  })

  it('422: текст сервера в плашке-alert и подсветка виновного поля', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    post.mockRejectedValueOnce(new ApiError(
      { kind: 'validation', code: 'bad_set', text: 'Setări invalide', field: 'name' }, 'v'))
    open()
    await screen.findByDisplayValue('Clinica Test')

    fireEvent.change(input('Nume'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))

    expect(await screen.findByText('Setări invalide')).toBeTruthy()
    expect(screen.getByRole('alert').getAttribute('data-kind')).toBe('err')
    expect(input('Nume').getAttribute('aria-invalid')).toBe('true')
    expect(input('Telefon').getAttribute('aria-invalid')).toBeNull()
    expect(input('Nume').disabled).toBe(false)
  })

  it('500 (save_err): текст сервера, поля не подсвечены', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    post.mockRejectedValueOnce(new ApiError(
      { kind: 'server', status: 500, code: 'save_err', text: 'Nu am putut scrie fișierul' }, 's'))
    open()
    await screen.findByDisplayValue('Clinica Test')
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText('Nu am putut scrie fișierul')).toBeTruthy()
    expect(document.querySelector('[aria-invalid]')).toBeNull()
  })

  it('сеть упала при сохранении: своя фраза, форма остаётся', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    post.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    open()
    await screen.findByDisplayValue('Clinica Test')
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText(/Programul nu răspunde/)).toBeTruthy()
    expect(input('Nume').value).toBe('Clinica Test')
  })

  it('B3: отказ в праве при загрузке — уход туда же, куда страница сервера; экран не монтируется', async () => {
    get.mockRejectedValueOnce(new ApiError(
      { kind: 'forbidden', code: 'no_access', text: 'Secțiunea este rezervată directorului' }, 'f'))
    const navigate = vi.fn()
    open(navigate)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin?msg=no_access'))
    await waitFor(() => expect(document.querySelector('.dp-react-root')).toBeNull())
    expect(screen.queryByText('Secțiunea este rezervată directorului')).toBeNull()
  })

  it('иной 403 при загрузке: текст сервера, без кнопки «повторить», со ссылкой на старую страницу', async () => {
    get.mockRejectedValueOnce(new ApiError(
      { kind: 'forbidden', code: 'bad_origin', text: 'Cerere respinsă' }, 'f'))
    open()
    expect(await screen.findByText('Cerere respinsă')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Reîncearcă/ })).toBeNull()
    expect(screen.queryByLabelText('Nume')).toBeNull()
    const link = screen.getByRole('link', { name: 'Varianta clasică' }) as HTMLAnchorElement
    expect(link.getAttribute('href')).toContain('?ui=legacy')
  })

  it('движок не ответил при загрузке: «повторить» запрашивает заново', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    get.mockResolvedValueOnce(ok(SAMPLE))
    open()
    expect(await screen.findByText(/Programul nu răspunde/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Reîncearcă/ }))
    expect(await screen.findByDisplayValue('Clinica Test')).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('401 при загрузке: уходит на вход движка, форму не рисует', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open(navigate)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=%2Fadmin%2Fsettings%2Fclinic'))
    expect(screen.queryByLabelText('Nume')).toBeNull()
  })

  it('401 при сохранении: тоже на вход', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    post.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open(navigate)
    await screen.findByDisplayValue('Clinica Test')
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1))
  })

  it('поля режут ввод по потолку сервера', async () => {
    get.mockResolvedValueOnce(ok(SAMPLE))
    open()
    await screen.findByDisplayValue('Clinica Test')
    expect(input('Nume').maxLength).toBe(80)
    expect(input('Telefon').maxLength).toBe(30)
    expect(input('Adresa (RO)').maxLength).toBe(120)
  })
})
