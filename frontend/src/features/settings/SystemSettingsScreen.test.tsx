import { cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import type { SystemData } from './settings'
import { openScreen } from '../../test/openScreen'
import { loadSystemSettings, SystemSettingsScreen } from './SystemSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const FRESH: SystemData = {
  version: '1.28.0',
  db: 'SQLite (local, data/dental.db)',
  folder: { path: 'C:\\ProgramData\\DentPilot', hint: 'aici stau evidența, documentele și copiile de rezervă' },
  telegram: '',
  update: { state: 'fresh', icon: 'check', text: 'la zi', latest: '1.28.0', url: '' },
  channel: null,
  access: { icon: 'lock', text: 'PIN setat' },
  bitlocker: { tone: 'ok', icon: 'check', text: 'activ pe C:' },
  feedback: 'suport@dentpilot.md',
  privacy: '<p>Programul funcționează local.</p>',
  uninstall: { found: true, version: '1.28.0', stale: false, hive: 'HKLM' },
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const open = (navigate?: (url: string) => void, pollMs = 1500) => openScreen(
  '/admin/settings/system', '/admin/settings/system',
  <SystemSettingsScreen pollMs={pollMs} {...(navigate ? { navigate } : {})} />, loadSystemSettings, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('SystemSettingsScreen', () => {
  it('состояние: версия, база, ПУТЬ к папке данных и проза о приватности', async () => {
    get.mockResolvedValueOnce(ok(FRESH))
    open(vi.fn())
    expect(await screen.findByText('v1.28.0')).toBeTruthy()
    expect(screen.getByText('SQLite (local, data/dental.db)')).toBeTruthy()
    /* ⭐ Единственное место, где директор сверяет, КУДА программа пишет.
       Путь целиком, а не «%ProgramData%»: сокращение глазами не сверить. */
    expect(screen.getByText('C:\\ProgramData\\DentPilot')).toBeTruthy()
    expect(screen.getByText(/aici stau evidența/)).toBeTruthy()
    expect(screen.getByText('PIN setat')).toBeTruthy()
    expect(screen.getByText('Programul funcționează local.')).toBeTruthy()
    /* Заморожённый бот и канал stable строк не дают вовсе. */
    expect(screen.queryByText('Canal Telegram')).toBeNull()
    expect(screen.queryByText('Canal actualizări')).toBeNull()
  })

  it('можно обновиться одним кликом: запуск остаётся ФОРМОЙ на старый маршрут', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      update: { state: 'self', icon: 'refresh', text: 'disponibilă 1.29.0', latest: '1.29.0', url: '' },
    }))
    open(vi.fn())
    const btn = await screen.findByRole('button', { name: /Actualizează acum/ })
    /* ⛔ Не fetch: маршрут подменяет сам exe и отвечает целой страницей,
       которая обязана работать, когда бандла под ней уже нет. */
    expect(btn.closest('form')?.getAttribute('action')).toBe('/admin/update/run')
    expect(btn.closest('form')?.getAttribute('method')).toBe('post')
  })

  it('файл не публикуется — только ссылка на релиз, без кнопки', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      update: { state: 'link', icon: 'refresh', text: 'disponibilă 1.29.0 — descărcați',
                latest: '1.29.0', url: 'https://example.invalid/r/1.29.0' },
    }))
    open(vi.fn())
    const link = await screen.findByRole('link', { name: /descărcați/ })
    expect(link.getAttribute('href')).toBe('https://example.invalid/r/1.29.0')
    expect(screen.queryByRole('button', { name: /Actualizează acum/ })).toBeNull()
  })

  it('«Verifică acum» меняет строку НА МЕСТЕ — второго запроса за состоянием нет', async () => {
    get.mockResolvedValueOnce(ok(FRESH))
    post.mockResolvedValueOnce(ok({
      ...FRESH,
      update: { state: 'link', icon: 'refresh', text: 'disponibilă 1.29.0 — descărcați',
                latest: '1.29.0', url: 'https://example.invalid/r/1.29.0' },
    }))
    open(vi.fn())
    await screen.findByText('la zi')
    fireEvent.click(screen.getByRole('button', { name: /Verifică acum/ }))
    expect(await screen.findByText(/disponibilă 1.29.0/)).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/system/check', {})
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('канал не stable виден намеренно: этот компьютер получает версии раньше клиник', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      channel: { name: 'beta (pre-lansări)',
                 warn: 'acest calculator vede versiunile ÎNAINTE de clinici',
                 note: ' · versiunea curentă din canal este pre-lansare' },
    }))
    open(vi.fn())
    expect(await screen.findByText('beta (pre-lansări)')).toBeTruthy()
    expect(screen.getByText(/ÎNAINTE de clinici/)).toBeTruthy()
    expect(screen.getByText(/pre-lansare/)).toBeTruthy()
  })

  it('BitLocker выключен — строка красная, как на старой странице', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      bitlocker: { tone: 'alarm', icon: 'ban', text: 'oprit — discul nu este criptat' },
    }))
    open(vi.fn())
    const cell = await screen.findByText(/discul nu este criptat/)
    expect(cell.className).toContain('dp-bl-alarm')
  })

  /* P4.1. Запись «Программ и компонентов» лежит в HKLM, программа идёт без
     повышения — поправить её она сама не может. Экран обязан показать это
     ФАКТОМ и дать кнопку, а не молчать и не показывать UAC сам. */
  it('версия сходится — ни строки, ни кнопки', async () => {
    get.mockResolvedValueOnce(ok(FRESH))
    open(vi.fn())
    await screen.findByText('v1.28.0')
    expect(screen.queryByRole('button', { name: /Corectează/ })).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })

  it('установка копированием — записи нет, чинить нечего', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      uninstall: { found: false, version: '', stale: false, hive: '' },
    }))
    open(vi.fn())
    await screen.findByText('v1.28.0')
    /* ⛔ Предлагать «исправить» там, где записи не существует, значит звать
       человека чинить то, чего нет. */
    expect(screen.queryByRole('button', { name: /Corectează/ })).toBeNull()
  })

  it('версия отстала — названа СТАРАЯ, и кнопка просит права', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      uninstall: { found: true, version: '1.20.0', stale: true, hive: 'HKLM' },
    }))
    post.mockResolvedValueOnce(ok({
      ...FRESH,
      uninstall: { found: true, version: '1.28.0', stale: false, hive: 'HKLM' },
    }))
    const { container } = open(vi.fn())
    await screen.findByRole('button', { name: /Corectează/ })
    /* ⭐ Названа та версия, что ВИДНА в Windows, а не своя: человек сверяет
       строку глазами со списком «Программ и компонентов». ⚠️ Текст разбит на
       узлы JSX, поэтому сверяется содержимое целиком, а не один элемент. */
    expect(container.textContent).toContain('scrie versiunea v1.20.0')
    expect(container.textContent).toContain('drepturi de administrator')
    expect(container.textContent).toContain('Datele clinicii nu sunt atinse')

    fireEvent.click(screen.getByRole('button', { name: /Corectează/ }))
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith(
      '/settings/system/uninstall-sync', {}))
    /* ⚠️ Итог окна UAC серверу не виден, поэтому экран верит только СВЕЖЕЙ
       модели: строка ушла — значит запись действительно поправлена. */
    await vi.waitFor(() =>
      expect(screen.queryByRole('button', { name: /Corectează/ })).toBeNull())
  })

  it('ответ пришёл ДО подтверждения UAC — экран перечитывает состояние, пока запись не поправлена', async () => {
    const stale = { found: true, version: '1.20.0', stale: true, hive: 'HKLM' }
    const fixed = { found: true, version: '1.28.0', stale: false, hive: 'HKLM' }
    /* загрузчик → запись старая; ответ кнопки — ЕЩЁ старая (окно только
       показано); дозор: раз старая, потом поправлена */
    let release: (v: ApiResult<SystemData>) => void = () => {}
    get.mockResolvedValueOnce(ok({ ...FRESH, uninstall: stale }))
    post.mockResolvedValueOnce(ok({ ...FRESH, uninstall: stale }))
    get.mockResolvedValueOnce(ok({ ...FRESH, uninstall: stale }))
    get.mockReturnValueOnce(new Promise<ApiResult<SystemData>>((r) => { release = r }))
    const { container } = open(vi.fn(), 0)
    fireEvent.click(await screen.findByRole('button', { name: /Corectează/ }))
    /* пока окно у человека — кнопка не даёт нажать второй раз, и это сказано */
    await vi.waitFor(() => expect(container.textContent).toContain('Se așteaptă confirmarea Windows'))
    expect((screen.getByRole('button', { name: /Corectează/ }) as HTMLButtonElement).disabled).toBe(true)
    /* второй круг дозора висит, пока человек в окне; подтвердил — запись
       поправлена, строка ушла ФАКТОМ, без смены страницы */
    await vi.waitFor(() => expect(get.mock.calls.filter((c) => c[0] === '/settings/system').length).toBe(3))
    release(ok({ ...FRESH, uninstall: fixed }))
    await vi.waitFor(() =>
      expect(screen.queryByRole('button', { name: /Corectează/ })).toBeNull())
    expect(container.textContent).not.toContain('Se așteaptă')
    expect(get.mock.calls.filter((c) => c[0] === '/settings/system').length).toBe(3)
  })
})
