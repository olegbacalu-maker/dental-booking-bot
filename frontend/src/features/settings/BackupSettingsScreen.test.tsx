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
  auto: { enabled: true, folder: '', last: { at: '17.10.2026 09:00', where: '' }, has_pass: false,
    pass_unreadable: false, local_at: '17.10.2026 09:00',
    local_error: '', ext_at: '', ext_error: '', ext_stale: false, stale_days: 3, keep: 7, alert: '' },
  restore: {
    local: [
      { name: 'dental_20261017_090000_1.db', made: '17.10.2026 09:00', day: '17.10.2026', size: 3 * 1024 * 1024 },
      { name: 'dental_20261016_210000_1.db', made: '16.10.2026 21:00', day: '16.10.2026', size: 2 * 1024 * 1024 },
      { name: 'dental_20261016_090000_1.db', made: '16.10.2026 09:00', day: '16.10.2026', size: 2 * 1024 * 1024 },
    ],
    archives: [], staged: null, pending: false, schema: 7,
  },
}
const OFF: BackupData = {
  ...DATA,
  auto: { ...DATA.auto, enabled: false, alert: '' },
}
const CONFIGURED: BackupData = {
  ...DATA,
  auto: { ...DATA.auto, folder: 'D:\\Copii', has_pass: true, ext_at: '17.10.2026 10:00',
    last: { at: '17.10.2026 10:00', where: 'D:\\Copii' } },
  restore: { ...DATA.restore, archives: [{ name: 'dentpilot-auto-20261017_1000.zip', made: '17.10.2026 10:00', day: '17.10.2026', size: 5 }] },
}
const STAGED: BackupData = {
  ...DATA,
  restore: {
    ...DATA.restore,
    staged: { kind: 'local', source: 'x', name: 'dental_20261017_090000_1.db', made: '17.10.2026 09:00',
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
  it('наверху — выключатель, строка-факт и ни одного имени файла (17.10 вечером)', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    const { container } = open(vi.fn())
    const sw = await screen.findByRole('switch', { name: 'Copie zilnică automată' }) as HTMLInputElement
    expect(sw.checked).toBe(true)
    /* Слово Олега: экран — для регистратуры. Факт «когда и куда» — да;
       data\backups, ротация, DPAPI, имена файлов — нет (они в FAQ). */
    expect(screen.getByText(/Ultima copie:/).textContent).toMatch(/17\.10\.2026 09:00, pe acest calculator/)
    expect(container.textContent).not.toMatch(/dental_2026|data\\backups|DPAPI|AES/)
  })

  it('выключатель шлёт ТОЛЬКО {enabled}: папку сервер не трогает (нет поля ≠ стереть)', async () => {
    get.mockResolvedValueOnce(ok(CONFIGURED))
    post.mockResolvedValueOnce(ok({ ...CONFIGURED, auto: { ...CONFIGURED.auto, enabled: false } },
      'ok_bkp_stop', 'Copia zilnică automată este oprită'))
    open(vi.fn())
    const sw = await screen.findByRole('switch', { name: 'Copie zilnică automată' })
    fireEvent.click(sw)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/backup/auto', { enabled: false }))
    expect(await screen.findByText('Copia zilnică automată este oprită')).toBeTruthy()
    /* Выключено — форма папки сложена, факт остаётся; история — на месте. */
    expect(screen.queryByLabelText(/Folderul copiei/)).toBeNull()
    expect(screen.getByText(/Ultima copie:/)).toBeTruthy()
    expect(screen.getByText(/Oprită: rămâne doar copia/)).toBeTruthy()
  })

  it('выключенное состояние молчит: ни янтарной строки, ни формы папки', async () => {
    get.mockResolvedValueOnce(ok(OFF))
    const { container } = open(vi.fn())
    await screen.findByRole('switch', { name: 'Copie zilnică automată' })
    expect(container.querySelector('.banner.warn')).toBeNull()
    expect(screen.queryByLabelText(/Folderul copiei/)).toBeNull()
  })

  it('янтарная строка — текст сервера, тот же, что у баннера директора', async () => {
    get.mockResolvedValueOnce(ok({ ...DATA, auto: { ...DATA.auto, alert: 'Copia de rezervă zilnică nu s-a făcut: disc plin' } }))
    open(vi.fn())
    expect(await screen.findByText(/nu s-a făcut: disc plin/)).toBeTruthy()
  })

  it('история копий — по дням, со счётом и размером, а не списком файлов', async () => {
    get.mockResolvedValueOnce(ok(CONFIGURED))
    const { container } = open(vi.fn())
    await screen.findByText('Copiile făcute')
    const rows = Array.from(container.querySelectorAll('.dp-bk-hist tr')).map((r) => r.textContent)
    /* Два дня локальных (одна и две копии), один день в папке; файлов по имени нет. */
    expect(rows).toEqual(['17.10.20261 copie3.0 MB', '16.10.20262 copii4.0 MB', '17.10.20261 copie1 KB'])
    /* Папка — в строке-факте, не в заголовке группы: длинный путь ломал карточку. */
    expect(screen.getByText('În folderul ales')).toBeTruthy()
  })

  it('папка и пароль уходят на сервер, даты — ФАКТЫ сервера', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockResolvedValueOnce(ok(CONFIGURED, 'ok_bkp_auto', 'Folderul copiei a fost salvat'))
    open(vi.fn())
    const folder = await screen.findByLabelText(/Folderul copiei/)
    fireEvent.change(folder, { target: { value: 'D:\\Copii' } })
    fireEvent.change(screen.getByLabelText(/parola copiei/), { target: { value: 'parola-lunga-12' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/backup/auto',
      { folder: 'D:\\Copii', password: 'parola-lunga-12' }))
    /* Ответ несёт всю модель: факт обновляется на месте, без второго запроса,
       а кнопка «Fă o copie acum» — только у настроенной. */
    expect((await screen.findByText(/Ultima copie:/)).textContent).toMatch(/17\.10\.2026 10:00, în D:\\Copii/)
    expect(screen.getByRole('button', { name: /Fă o copie acum/ })).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(1)
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

  it('выгрузка идёт ОБЫЧНОЙ формой на старый маршрут, а не через fetch', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    const { container } = open(vi.fn())
    await screen.findByRole('button', { name: /Exportă arhiva/ })
    /* ⛔ Главное свойство экрана, и оно невидимо глазами: архив весит сотни
       мегабайт, браузер качает ответ формы потоком и показывает ход. Прочитай
       его fetch'ем ради «React» — клиника получила бы зависшую страницу без
       единой ошибки. Поэтому проверяется САМА форма, а не кнопка. */
    const form = container.querySelector(`form[action="${EXPORT_ACTION}"]`)
    expect(form?.getAttribute('method')).toBe('post')
    expect(post).not.toHaveBeenCalled()
  })

  it('пока данных нет — ни одного поля и ни одной кнопки', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    const { container } = open(vi.fn())
    /* ⛔ Форма выгрузки с пустым minLength ушла бы на сервер без ограничения
       вовсе — а пароль здесь единственное, чем закрыт архив с картотекой.
       Поэтому до данных форм на экране нет совсем. */
    expect(container.querySelector('input')).toBeNull()
    expect(container.querySelector('button')).toBeNull()
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

  it('восстановление сложено: выбор копии по дате, сперва ЧТО ВНУТРИ, подтверждение — через окно', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    post.mockResolvedValueOnce(ok(STAGED, 'ok_rst_staged', 'Copia a fost verificată'))
    const { container } = open(vi.fn())
    const fold = (await screen.findByText('Restaurare din copie')).closest('details')
    expect(fold?.open).toBe(false)
    const pick = screen.getByLabelText('Copia') as HTMLSelectElement
    /* Список — по датам, не по именам файлов. */
    expect(Array.from(pick.options).map((o) => o.textContent)).toEqual(
      ['— alegeți copia —', '17.10.2026 09:00', '16.10.2026 21:00', '16.10.2026 09:00'])
    expect(container.textContent).not.toMatch(/dental_20261017/)
    fireEvent.change(pick, { target: { value: 'local:dental_20261017_090000_1.db' } })
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
