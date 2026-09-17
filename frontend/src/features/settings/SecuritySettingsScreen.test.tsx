import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { BackupData, SecurityData } from './settings'
import { BackupSettingsScreen } from './BackupSettingsScreen'
import { SecuritySettingsScreen } from './SecuritySettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const SEC: SecurityData = {
  users: [
    { id: 'clinic', name: 'Director', role: 'director', doctor_id: '', last_login: '13.08.2026 14:02' },
    { id: 'ana', name: 'Ana R', role: 'receptie', doctor_id: '', last_login: '' },
  ],
  roles: { director: 'Director', receptie: 'Recepție', medic: 'Medic' },
  doctors: [{ id: 'd2', name: 'Dr. Doi' }],
  me: 'clinic',
  pin: { min: 4, max: 8 },
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('SecuritySettingsScreen', () => {
  it('учётки: имя, id, последний вход, роль и врач в строке', async () => {
    get.mockResolvedValueOnce(ok(SEC))
    render(<SecuritySettingsScreen />)
    expect(await screen.findByText('Director')).toBeTruthy()
    expect(screen.getByText(/13.08.2026 14:02/)).toBeTruthy()
    expect(screen.getByText(/id: ana/)).toBeTruthy()
    expect((screen.getByLabelText('rol ana') as HTMLSelectElement).value).toBe('receptie')
    expect((screen.getByLabelText('medic clinic') as HTMLSelectElement).value).toBe('')
    expect(screen.getByText(/ultima intrare: —/)).toBeTruthy()
  })

  it('смена PIN: шлёт три поля, показывает ответ, чистит форму', async () => {
    get.mockResolvedValueOnce(ok(SEC))
    post.mockResolvedValueOnce(ok(undefined, 'ok_pin', 'PIN schimbat'))
    render(<SecuritySettingsScreen />)
    await screen.findByText('Director')
    fireEvent.change(screen.getByLabelText('PIN actual'), { target: { value: '4321' } })
    fireEvent.change(screen.getByLabelText('PIN nou'), { target: { value: '5678' } })
    fireEvent.change(screen.getByLabelText('repetați'), { target: { value: '5678' } })
    fireEvent.click(screen.getByRole('button', { name: 'Schimbă' }))
    expect(await screen.findByText('PIN schimbat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/pin', { old_pin: '4321', new1: '5678', new2: '5678' })
    expect((screen.getByLabelText('PIN actual') as HTMLInputElement).value).toBe('')
  })

  it('смена PIN: отказ сервера словами', async () => {
    get.mockResolvedValueOnce(ok(SEC))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_pin', text: 'PIN greșit' }, 'v'))
    render(<SecuritySettingsScreen />)
    await screen.findByText('Director')
    fireEvent.change(screen.getByLabelText('PIN actual'), { target: { value: '0000' } })
    fireEvent.change(screen.getByLabelText('PIN nou'), { target: { value: '5678' } })
    fireEvent.change(screen.getByLabelText('repetați'), { target: { value: '5678' } })
    fireEvent.click(screen.getByRole('button', { name: 'Schimbă' }))
    expect(await screen.findByText('PIN greșit')).toBeTruthy()
  })

  it('правка строки: роль и новый PIN уезжают с id учётки, список подменяется ответом', async () => {
    get.mockResolvedValueOnce(ok(SEC))
    post.mockResolvedValueOnce(ok({ ...SEC, users: [SEC.users[0]!, { ...SEC.users[1]!, role: 'medic', doctor_id: 'd2' }] }, 'ok_user', 'Cont salvat'))
    render(<SecuritySettingsScreen />)
    await screen.findByText('Director')
    fireEvent.change(screen.getByLabelText('rol ana'), { target: { value: 'medic' } })
    fireEvent.change(screen.getByLabelText('medic ana'), { target: { value: 'd2' } })
    fireEvent.change(screen.getByLabelText('PIN ana'), { target: { value: '7777' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Salvează' })[1] as HTMLButtonElement)
    expect(await screen.findByText('Cont salvat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/users', { uid: 'ana', name: 'Ana R', role: 'medic', doctor_id: 'd2', pin: '7777' })
    expect((screen.getByLabelText('PIN ana') as HTMLInputElement).value).toBe('')
  })

  it('новая учётка: форма добавления шлёт все поля и очищается', async () => {
    get.mockResolvedValueOnce(ok(SEC))
    post.mockResolvedValueOnce(ok({ ...SEC, users: [...SEC.users, { id: 'd2', name: 'Dr. Doi', role: 'medic', doctor_id: 'd2', last_login: '' }] }, 'ok_user', 'Cont salvat'))
    render(<SecuritySettingsScreen />)
    await screen.findByText('Director')
    fireEvent.change(screen.getByLabelText('Nume și prenume'), { target: { value: 'Dr. Doi' } })
    fireEvent.change(screen.getByLabelText('id (ex. d2, ana)'), { target: { value: 'd2' } })
    fireEvent.change(screen.getByLabelText('medic'), { target: { value: 'd2' } })
    fireEvent.change(screen.getByLabelText('PIN 4–8 cifre'), { target: { value: '2222' } })
    fireEvent.click(screen.getByRole('button', { name: '+ Adaugă utilizator' }))
    expect(await screen.findByText('Cont salvat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/users', { uid: 'd2', name: 'Dr. Doi', role: 'medic', doctor_id: 'd2', pin: '2222' })
    expect(screen.getByText(/id: d2/)).toBeTruthy()
    expect((screen.getByLabelText('Nume și prenume') as HTMLInputElement).value).toBe('')
  })

  it('удаление: подтверждение, POST по id, отказ «последний директор» словами', async () => {
    get.mockResolvedValueOnce(ok(SEC))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'last_dir', text: 'cel puțin un director' }, 'c'))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    render(<SecuritySettingsScreen />)
    await screen.findByText('Director')
    fireEvent.click(screen.getAllByRole('button', { name: 'Șterge' })[0] as HTMLButtonElement)
    expect(await screen.findByText('cel puțin un director')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/users/clinic/delete', {})
    expect(window.confirm).toHaveBeenCalledWith('Ștergeți contul Director?')
  })

  it('секции нет (404): своя фраза', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 'nf'))
    render(<SecuritySettingsScreen />)
    expect(await screen.findByText(/doar în ediția instalată/)).toBeTruthy()
  })
})

describe('BackupSettingsScreen', () => {
  it('форма выгрузки бьёт в старый маршрут обычным POST, порог пароли с сервера', async () => {
    get.mockResolvedValueOnce(ok<BackupData>({ min_pass: 10, filename: 'dentpilot-backup.zip' }))
    render(<BackupSettingsScreen />)
    expect(await screen.findByRole('button', { name: /Exportă arhiva/ })).toBeTruthy()
    const form = document.querySelector('form') as HTMLFormElement
    expect(form.getAttribute('action')).toBe('/admin/backup/export')
    expect(form.getAttribute('method')).toBe('post')
    const pw = screen.getByLabelText('parolă (min. 10 caractere)') as HTMLInputElement
    expect(pw.minLength).toBe(10)
    expect(pw.name).toBe('parola')
    expect(post).not.toHaveBeenCalled()
  })
})
