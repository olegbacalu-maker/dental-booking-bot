import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../types/api'
import type { ApiResult } from '../../services/api'
import type { BackupData } from './settings'
import { BackupSettingsScreen, EXPORT_ACTION } from './BackupSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const DATA: BackupData = { min_pass: 8, filename: 'dentpilot-2026-09-21.zip' }
const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
/* Отказ ПРИЛЕТАЕТ исключением, а не возвращается значением: так его подаёт
   `services/api`, и тест, подделавший форму ответа, проверял бы свою выдумку. */
const boom = (status: number) =>
  new ApiError({ kind: 'server', status, code: '', text: '' }, `s${status}`)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('BackupSettingsScreen', () => {
  it('выгрузка идёт ОБЫЧНОЙ формой на старый маршрут, а не через fetch', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    const { container } = render(<BackupSettingsScreen navigate={vi.fn()} />)
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
    render(<BackupSettingsScreen navigate={vi.fn()} />)
    const input = await screen.findByLabelText(/min\. 8 caractere/)
    /* Своё число здесь разошлось бы с `bkp.MIN_PASS` молча: браузер пустил бы
       короткую паролю, а сервер вернул бы отказ — и человек чинил бы не то. */
    expect(input.getAttribute('minLength')).toBe('8')
    expect(input.getAttribute('required')).not.toBeNull()
    expect(input.getAttribute('type')).toBe('password')
  })

  it('пока данных нет — ни поля, ни кнопки нажать нельзя', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    const { container } = render(<BackupSettingsScreen navigate={vi.fn()} />)
    /* ⛔ Иначе форма уйдёт на сервер с пустым minLength, то есть без ограничения
       вовсе, — а пароль здесь единственное, чем закрыт архив с картотекой. */
    expect(container.querySelector('input')?.hasAttribute('disabled')).toBe(true)
    expect(container.querySelector('button')?.hasAttribute('disabled')).toBe(true)
    expect(container.querySelector('section')?.getAttribute('aria-busy')).toBe('true')
  })

  it('облако: 404 объясняется словами, а не общим «не загрузилось»', async () => {
    get.mockRejectedValueOnce(boom(404))
    render(<BackupSettingsScreen navigate={vi.fn()} />)
    /* Копия существует только в установленной редакции. Общий текст отказа
       отправил бы человека чинить сеть там, где чинить нечего. */
    expect(await screen.findByText(/doar în ediția instalată/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Exportă arhiva/ })).toBeNull()
  })

  it('обычный отказ НЕ выдаётся за облако', async () => {
    get.mockRejectedValueOnce(boom(500))
    render(<BackupSettingsScreen navigate={vi.fn()} />)
    await screen.findByRole('button', { name: /Reîncearcă/ })
    expect(screen.queryByText(/doar în ediția instalată/)).toBeNull()
  })
})
