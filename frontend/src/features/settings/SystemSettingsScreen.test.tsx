import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import type { SystemData } from './settings'
import { SystemSettingsScreen } from './SystemSettingsScreen'

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
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('SystemSettingsScreen', () => {
  it('состояние: версия, база, ПУТЬ к папке данных и проза о приватности', async () => {
    get.mockResolvedValueOnce(ok(FRESH))
    render(<SystemSettingsScreen navigate={vi.fn()} />)
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
    render(<SystemSettingsScreen navigate={vi.fn()} />)
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
    render(<SystemSettingsScreen navigate={vi.fn()} />)
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
    render(<SystemSettingsScreen navigate={vi.fn()} />)
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
    render(<SystemSettingsScreen navigate={vi.fn()} />)
    expect(await screen.findByText('beta (pre-lansări)')).toBeTruthy()
    expect(screen.getByText(/ÎNAINTE de clinici/)).toBeTruthy()
    expect(screen.getByText(/pre-lansare/)).toBeTruthy()
  })

  it('BitLocker выключен — строка красная, как на старой странице', async () => {
    get.mockResolvedValueOnce(ok({
      ...FRESH,
      bitlocker: { tone: 'alarm', icon: 'ban', text: 'oprit — discul nu este criptat' },
    }))
    render(<SystemSettingsScreen navigate={vi.fn()} />)
    const cell = await screen.findByText(/discul nu este criptat/)
    expect(cell.className).toContain('dp-bl-alarm')
  })
})
