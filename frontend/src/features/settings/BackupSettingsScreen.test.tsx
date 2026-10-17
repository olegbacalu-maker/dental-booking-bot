import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../types/api'
import type { ApiResult } from '../../services/api'
import type { BackupData } from './settings'
import { openScreen } from '../../test/openScreen'
import { BackupSettingsScreen, EXPORT_ACTION, loadBackupSettings } from './BackupSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const DATA: BackupData = {
  min_pass: 8, filename: 'dentpilot-2026-09-21.zip',
  auto: { folder: '', has_pass: false, pass_unreadable: false, local_at: '17.10.2026 09:00',
    local_error: '', ext_at: '', ext_error: '', ext_stale: false, stale_days: 3, keep: 7, alert: '' },
  restore: {
    local: [{ name: 'dental_20261017_090000_1.db', made: '2026-10-17 09:00', size: 1000 }],
    archives: [], staged: null, pending: false, schema: 7,
  },
}
const CONFIGURED: BackupData = {
  ...DATA,
  auto: { ...DATA.auto, folder: 'D:\\Copii', has_pass: true, ext_at: '17.10.2026 10:00' },
  restore: { ...DATA.restore, archives: [{ name: 'dentpilot-auto-20261017_1000.zip', made: '17.10.2026 10:00', size: 5 }] },
}
const STAGED: BackupData = {
  ...DATA,
  restore: {
    ...DATA.restore,
    staged: { kind: 'local', source: 'x', name: 'dental_20261017_090000_1.db', made: '2026-10-17 09:00',
      files: 0, encrypted: false, clinic: '', patients: 42, appointments: 7, documents: 3, schema: 7 },
  },
}
const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
/* Отказ ПРИЛЕТАЕТ исключением, а не возвращается значением: так его подаёт
   `services/api`, и тест, подделавший форму ответа, проверял бы свою выдумку. */
const boom = (status: number) =>
  new ApiError({ kind: 'server', status, code: '', text: '' }, `s${status}`)

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/settings/backup', '/admin/settings/backup',
  <BackupSettingsScreen {...(navigate ? { navigate } : {})} />, loadBackupSettings, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('BackupSettingsScreen', () => {
  it('выгрузка идёт ОБЫЧНОЙ формой на старый маршрут, а не через fetch', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    const { container } = open(vi.fn())
    await screen.findByRole('button', { name: /Exportă arhiva/ })
    /* ⛔ Главное свойство экрана, и оно невидимо глазами: архив весит сотни
       мегабайт, браузер качает ответ формы потоком и показывает ход. Прочитай
       его fetch'ем ради «React» — клиника получила бы зависшую страницу без
       единой ошибки. Поэтому проверяется САМА форма, а не кнопка. */
    const form = container.querySelector('form')
    expect(form?.getAttribute('method')).toBe('post')
    expect(form?.getAttribute('action')).toBe(EXPORT_ACTION)
    expect(post).not.toHaveBeenCalled()
  })

  it('минимальная длина пароля приходит С СЕРВЕРА, а не зашита в экран', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    open(vi.fn())
    const input = await screen.findByLabelText(/^parolă \(min\. 8 caractere\)/)
    /* Своё число здесь разошлось бы с `bkp.MIN_PASS` молча: браузер пустил бы
       короткую паролю, а сервер вернул бы отказ — и человек чинил бы не то. */
    expect(input.getAttribute('minLength')).toBe('8')
    expect(input.getAttribute('required')).not.toBeNull()
    expect(input.getAttribute('type')).toBe('password')
  })

  it('пока данных нет — ни поля, ни кнопки нажать нельзя', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    const { container } = open(vi.fn())
    /* ⛔ Иначе форма уйдёт на сервер с пустым minLength, то есть без ограничения
       вовсе, — а пароль здесь единственное, чем закрыт архив с картотекой. */
    expect(container.querySelector('input')?.hasAttribute('disabled')).toBe(true)
    expect(container.querySelector('button')?.hasAttribute('disabled')).toBe(true)
    expect(container.querySelector('section')?.getAttribute('aria-busy')).toBe('true')
  })

  it('облако: 404 объясняется словами, а не общим «не загрузилось»', async () => {
    get.mockRejectedValueOnce(boom(404))
    open(vi.fn())
    /* Копия существует только в установленной редакции. Общий текст отказа
       отправил бы человека чинить сеть там, где чинить нечего. */
    expect(await screen.findByText(/doar în ediția instalată/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Exportă arhiva/ })).toBeNull()
  })

  it('обычный отказ НЕ выдаётся за облако', async () => {
    get.mockRejectedValueOnce(boom(500))
    open(vi.fn())
    await screen.findByRole('button', { name: /Reîncearcă/ })
    expect(screen.queryByText(/doar în ediția instalată/)).toBeNull()
  })

  it('внешняя копия: папка и пароль уходят на сервер, даты — ФАКТЫ сервера', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockResolvedValueOnce(ok(CONFIGURED, 'ok_bkp_auto', 'Copia de rezervă automată a fost setată'))
    open(vi.fn())
    const folder = await screen.findByLabelText(/Folderul copiei/)
    fireEvent.change(folder, { target: { value: 'D:\\Copii' } })
    fireEvent.change(screen.getByLabelText(/parola arhivelor/), { target: { value: 'parola-lunga-12' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/backup/auto',
      { folder: 'D:\\Copii', password: 'parola-lunga-12' }))
    /* Ответ несёт всю модель: дата последней внешней копии появляется на месте,
       без второго запроса, а кнопка «Fă o copie acum» — только у настроенной. */
    expect(await screen.findByText('17.10.2026 10:00')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Fă o copie acum/ })).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('восстановление: сперва ЧТО ВНУТРИ, подтверждение — через окно, заказ — на сервер', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockResolvedValueOnce(ok(STAGED, 'ok_rst_staged', 'Copia a fost verificată'))
    open(vi.fn())
    const radio = await screen.findByRole('radio', { name: /dental_20261017_090000_1\.db/ })
    fireEvent.click(radio)
    fireEvent.click(screen.getByRole('button', { name: /Verifică copia/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/backup/restore/stage',
      { kind: 'local', name: 'dental_20261017_090000_1.db' }))
    /* Число пациентов — ответ на «это точно та копия?», и он виден ДО кнопки. */
    expect(await screen.findByText('42')).toBeTruthy()
    const confirm = screen.getByRole('button', { name: /Restaurează la următoarea pornire/ })
    /* Отказ в окне — заказа нет; согласие — заказ уходит на сервер. */
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    fireEvent.click(confirm)
    await new Promise((r) => setTimeout(r, 0))
    expect(post).toHaveBeenCalledTimes(1)
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    post.mockResolvedValueOnce(ok({ ...STAGED, restore: { ...STAGED.restore, staged: null, pending: true },
      restart: false, text: '', note: '' }, 'ok_rst_ordered', 'Restaurarea se face la următoarea pornire'))
    fireEvent.click(confirm)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/backup/restore/confirm', {}))
    expect(await screen.findByText(/Restaurarea este comandată/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Verifică copia/ })).toBeNull()
  })

  it('заказ, ждущий старта, можно снять', async () => {
    get.mockResolvedValueOnce(ok({ ...DATA, restore: { ...DATA.restore, pending: true } }))
    post.mockResolvedValueOnce(ok(DATA, 'ok_rst_cancel', 'Restaurarea a fost anulată'))
    open(vi.fn())
    fireEvent.click(await screen.findByRole('button', { name: /Anulează restaurarea/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/backup/restore/cancel', {}))
    expect(await screen.findByRole('button', { name: /Verifică copia/ })).toBeTruthy()
  })
})
