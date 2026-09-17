import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { DoctorsList } from './doctors'
import { DoctorsListScreen } from './DoctorsListScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const LIST: DoctorsList = {
  doctors: [
    { id: 'd2', name: 'Dr. Activ Doi', spec: 'Chirurgie', status: 'activ', room: '3', phone: '101',
      hours: 'L–V 9:00–17:00', color: '#3B82F6', initials: 'AD', photo: '', archived: false,
      stats: { n: 4, pct: 25, noshow: 1 } },
    { id: 'd1', name: 'Dr. Arhivat Unu', spec: '', status: 'arhivat', room: '', phone: '',
      hours: 'ca al clinicii', color: '#10B981', initials: 'AU', photo: '/admin/doctor-photo/d1?v=x',
      archived: true, stats: { n: 0, pct: 0, noshow: 0 } },
  ],
  same_color: false,
  states: { activ: 'Activ', concediu: 'În concediu', arhivat: 'Arhivat' },
}

function ok<T>(data: T, code = '', text = ''): ApiResult<T> {
  return { data, code, text, tone: 'ok' }
}

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('DoctorsListScreen', () => {
  it('загрузка: форма добавления занята', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    render(<DoctorsListScreen />)
    expect(document.querySelector('section')?.getAttribute('aria-busy')).toBe('true')
    expect((screen.getByLabelText('Dr. Nume Prenume') as HTMLInputElement).disabled).toBe(true)
  })

  it('успех: карточки, подписи состояний с сервера, архив отдельно', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    render(<DoctorsListScreen />)
    expect(await screen.findByText('Dr. Activ Doi')).toBeTruthy()
    expect(screen.getByText('Activ').className).toContain('dbadge activ')
    expect(screen.getByText('Arhivat').className).toContain('dbadge arhivat')
    expect(screen.getByText('Arhivă')).toBeTruthy()
    expect(screen.getByText('L–V 9:00–17:00')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    const link = screen.getByText('Dr. Activ Doi').closest('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/admin/doctor-card/d2')
    expect(link.className).toBe('medcard')
    expect((screen.getByText('Dr. Arhivat Unu').closest('a') as HTMLAnchorElement).className).toBe('medcard off')
    expect(document.querySelector('img')?.getAttribute('src')).toBe('/admin/doctor-photo/d1?v=x')
    expect(screen.queryByText(/aceeași culoare/)).toBeNull()
  })

  it('пусто: ни одного врача — подсказка, форма открыта', async () => {
    get.mockResolvedValueOnce(ok({ ...LIST, doctors: [] }))
    render(<DoctorsListScreen />)
    expect(await screen.findByText(/Niciun medic/)).toBeTruthy()
    expect((screen.getByLabelText('Dr. Nume Prenume') as HTMLInputElement).disabled).toBe(false)
  })

  it('добавление: шлёт имя и специализацию, уходит в фишу нового с плашкой сервера', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    post.mockResolvedValueOnce(ok({ id: 'd5' }, 'new_med', 'Medic adăugat'))
    const navigate = vi.fn()
    render(<DoctorsListScreen navigate={navigate} />)
    await screen.findByText('Dr. Activ Doi')
    fireEvent.change(screen.getByLabelText('Dr. Nume Prenume'), { target: { value: 'Dr. Cinci' } })
    fireEvent.change(screen.getByLabelText('Specializare (ex. Terapie)'), { target: { value: 'Orto' } })
    fireEvent.click(screen.getByRole('button', { name: '+ Adaugă medic' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/doctor-card/d5?msg=new_med'))
    expect(post).toHaveBeenCalledWith('/doctors', { name: 'Dr. Cinci', spec: 'Orto' })
  })

  it('добавление: тёзка — текст сервера в плашке, форма остаётся', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'dup_med', text: 'Există deja un medic' }, 'c'))
    render(<DoctorsListScreen />)
    await screen.findByText('Dr. Activ Doi')
    fireEvent.change(screen.getByLabelText('Dr. Nume Prenume'), { target: { value: 'Dr. Activ Doi' } })
    fireEvent.click(screen.getByRole('button', { name: '+ Adaugă medic' }))
    expect(await screen.findByText('Există deja un medic')).toBeTruthy()
    expect((screen.getByLabelText('Dr. Nume Prenume') as HTMLInputElement).disabled).toBe(false)
  })

  it('одинаковые цвета: подсказка и сброс перечитывают список', async () => {
    get.mockResolvedValueOnce(ok({ ...LIST, same_color: true }))
    post.mockResolvedValueOnce(ok(undefined, 'ok_med', 'Datele medicului au fost salvate'))
    get.mockResolvedValueOnce(ok(LIST))
    render(<DoctorsListScreen />)
    expect(await screen.findByText(/aceeași culoare/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Culori automate/ }))
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    await waitFor(() => expect(screen.queryByText(/aceeași culoare/)).toBeNull())
    expect(post).toHaveBeenCalledWith('/doctors/colors', {})
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('движок не ответил: повтор', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    get.mockResolvedValueOnce(ok(LIST))
    render(<DoctorsListScreen />)
    fireEvent.click(await screen.findByRole('button', { name: /Reîncearcă/ }))
    expect(await screen.findByText('Dr. Activ Doi')).toBeTruthy()
  })

  it('401: на вход, ничего не рисует', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    render(<DoctorsListScreen navigate={navigate} />)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
    expect(screen.queryByLabelText('Dr. Nume Prenume')).toBeNull()
  })
})
