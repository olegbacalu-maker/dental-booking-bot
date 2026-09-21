import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import type { PatientRow, PatientsPage } from '../patients/patients'
import { QuickFind } from './QuickFind'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const row = (id: number, name: string, phone = '', doctor = ''): PatientRow => ({
  id, name, initials: name.slice(0, 2).toUpperCase(), phone, email: '',
  channel: 'manual', birth: '', age: null, doctor, doctor_own: false,
  last: '', next: '', n_visits: 0, debt: 0, status: 'activ', archived: false,
} as PatientRow)

const page = (rows: PatientRow[]): ApiResult<PatientsPage> => ({
  data: { rows, total: rows.length, page: 1, pages: 1, per: 8 } as PatientsPage,
  code: '', text: '', tone: 'ok',
})

const openIt = () => fireEvent.keyDown(document, { key: 'k', ctrlKey: true })

afterEach(() => {
  cleanup()
  get.mockReset()
  vi.restoreAllMocks()
})

describe('QuickFind', () => {
  it('закрыт, пока не позвали: ни узла, ни запроса', () => {
    const { container } = render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    expect(container.textContent).toBe('')
    expect(get).not.toHaveBeenCalled()
  })

  it('Ctrl+K открывает откуда угодно, Esc закрывает', async () => {
    const { container } = render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    openIt()
    const input = await screen.findByLabelText(/Nume sau telefon/)
    expect(input).toBeTruthy()
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(container.textContent).toBe('')
  })

  it('одна буква запроса НЕ шлёт: это была бы выдача по всей картотеке', async () => {
    render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    openIt()
    fireEvent.change(await screen.findByLabelText(/Nume sau telefon/),
                     { target: { value: 'I' } })
    await vi.waitFor(() => expect(screen.getByText(/două caractere/)).toBeTruthy())
    expect(get).not.toHaveBeenCalled()
  })

  it('телефон и врач показаны — ими различают однофамильцев', async () => {
    get.mockResolvedValue(page([row(1, 'Ion Popescu', '069000001', 'Dr. Damir Ion'),
                                row(2, 'Ion Popescu', '069000002', 'Medic 1')]))
    const { container } = render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    openIt()
    fireEvent.change(await screen.findByLabelText(/Nume sau telefon/),
                     { target: { value: 'Ion' } })
    await vi.waitFor(() => expect(screen.getAllByRole('button').length).toBe(2))
    /* ⛔ Без этих двух полей список красив и бесполезен: два «Ion Popescu»
       неразличимы, и регистратура откроет не ту фишу. */
    expect(container.textContent).toContain('069000001')
    expect(container.textContent).toContain('Dr. Damir Ion')
  })

  it('стрелки ведут выбор, Enter открывает фишу ВЫБРАННОГО', async () => {
    get.mockResolvedValue(page([row(11, 'Ana'), row(22, 'Bogdan'), row(33, 'Cezar')]))
    const navigate = vi.fn()
    render(<QuickFind navigate={navigate} debounceMs={0} />)
    openIt()
    const input = await screen.findByLabelText(/Nume sau telefon/)
    fireEvent.change(input, { target: { value: 'a' } })
    fireEvent.change(input, { target: { value: 'an' } })
    await vi.waitFor(() => expect(screen.getAllByRole('button').length).toBe(3))
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    /* ⚠️ Именно третий: проверка на «открылся хоть кто-то» пережила бы
       экран, который всегда открывает первого. */
    expect(navigate).toHaveBeenCalledWith('/admin/patient/33')
  })

  it('выбор по кругу: вверх с первого ведёт на последнего', async () => {
    get.mockResolvedValue(page([row(11, 'Ana'), row(22, 'Bogdan')]))
    const navigate = vi.fn()
    render(<QuickFind navigate={navigate} debounceMs={0} />)
    openIt()
    const input = await screen.findByLabelText(/Nume sau telefon/)
    fireEvent.change(input, { target: { value: 'an' } })
    await vi.waitFor(() => expect(screen.getAllByRole('button').length).toBe(2))
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(navigate).toHaveBeenCalledWith('/admin/patient/22')
  })

  it('ничего не нашлось — так и говорит, а не молчит', async () => {
    get.mockResolvedValue(page([]))
    render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    openIt()
    fireEvent.change(await screen.findByLabelText(/Nume sau telefon/),
                     { target: { value: 'zzz' } })
    expect(await screen.findByText('Nimic găsit')).toBeTruthy()
  })

  it('закрыли и позвали снова — поле чистое, чужого запроса нет', async () => {
    get.mockResolvedValue(page([row(11, 'Ana')]))
    render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    openIt()
    const input = await screen.findByLabelText(/Nume sau telefon/)
    fireEvent.change(input, { target: { value: 'Ana' } })
    await vi.waitFor(() => expect(screen.getAllByRole('button').length).toBe(1))
    fireEvent.keyDown(input, { key: 'Escape' })
    openIt()
    expect((await screen.findByLabelText(/Nume sau telefon/) as HTMLInputElement).value)
      .toBe('')
  })

  it('«Toți pacienții» уносит запрос на полный экран поиска', async () => {
    get.mockResolvedValue(page([row(11, 'Ana')]))
    render(<QuickFind navigate={vi.fn()} debounceMs={0} />)
    openIt()
    fireEvent.change(await screen.findByLabelText(/Nume sau telefon/),
                     { target: { value: 'Ana' } })
    const link = await screen.findByRole('link', { name: /Toți pacienții/ })
    expect(link.getAttribute('href')).toBe('/admin/search?q=Ana')
  })
})
