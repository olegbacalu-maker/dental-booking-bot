import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { DoctorCard } from './doctors'
import { DoctorCardScreen } from './DoctorCardScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const CARD: DoctorCard = {
  id: 'd2', name: 'Dr. Activ Doi', spec: 'Chirurgie', room: '3', phone: '101', email: '',
  status: 'activ', color: '#3B82F6', auto_color: true, work_from: null, work_to: null,
  hours: { min: 7, max: 21 }, initials: 'AD', photo: '', max_photo_mb: 5, future: 2,
  stats: { n: 4, pct: 25, noshow: 1 }, warning: '',
  week: [
    { date: '2026-09-17', label: 'Azi', dm: '17.09', count: 2, open: true },
    { date: '2026-09-18', label: 'Vi', dm: '18.09', count: 0, open: true },
    { date: '2026-09-19', label: 'Sâ', dm: '19.09', count: 0, open: false },
    { date: '2026-09-20', label: 'Du', dm: '20.09', count: 0, open: false },
    { date: '2026-09-21', label: 'Lu', dm: '21.09', count: 1, open: true },
    { date: '2026-09-22', label: 'Ma', dm: '22.09', count: 0, open: true },
    { date: '2026-09-23', label: 'Mi', dm: '23.09', count: 0, open: true },
  ],
  today: [
    { id: 7, time: '09:00', patient: 'Ion Pop', patient_id: 3, phone: '060', service: 'Consultație',
      status: 'confirmed', status_label: 'confirmată', note: false, comment: 'de sunat' },
    { id: 8, time: '10:00', patient: '', patient_id: null, phone: '', service: 'pauză',
      status: 'confirmed', status_label: 'confirmată', note: true, comment: '' },
  ],
  services: [
    { id: 'consult', name: 'Consultație', checked: true, note: 'toți medicii' },
    { id: 'hygiene', name: 'Igienizare', checked: false, note: '1 medic' },
  ],
  states: {
    activ: { label: 'Activ', hint: 'apare în programări' },
    concediu: { label: 'În concediu', hint: 'temporar nu primește' },
    arhivat: { label: 'Arhivat', hint: 'a plecat' },
  },
}

function ok<T>(data: T, code = '', text = ''): ApiResult<T> {
  return { data, code, text, tone: 'ok' }
}

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  postForm.mockReset()
})

describe('DoctorCardScreen', () => {
  it('успех: шапка, поля формы, неделя, сегодня, услуги, цифры', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    render(<DoctorCardScreen dk="d2" />)
    expect(await screen.findByText('Chirurgie')).toBeTruthy()
    expect(input('Nume').value).toBe('Dr. Activ Doi')
    expect(input('Cabinet').value).toBe('3')
    expect((screen.getByLabelText('de la') as HTMLSelectElement).value).toBe('')
    expect((screen.getByLabelText('Starea medicului') as HTMLSelectElement).value).toBe('activ')
    expect(screen.getByText('Activ').className).toContain('dbadge activ')
    // неделя: 7 ссылок на день врача, закрытый день без числа
    const cells = document.querySelectorAll('a.dp-daycell')
    expect(cells.length).toBe(7)
    expect(cells[0]?.getAttribute('href')).toBe('/admin/doctor/d2?date=2026-09-17')
    expect(cells[2]?.textContent).toContain('—')
    // сегодня: пациент ссылкой на фишу, заметка без ссылки
    expect(screen.getByText('Astăzi, 17.09.2026')).toBeTruthy()
    expect((screen.getByText('Ion Pop') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/patient/3')
    expect(screen.getByText('de sunat')).toBeTruthy()
    expect(screen.getAllByText('confirmată').length).toBe(2)
    // услуги и цифры
    expect((screen.getByLabelText(/Consultație/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/Igienizare/) as HTMLInputElement).checked).toBe(false)
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
    expect(get).toHaveBeenCalledWith('/doctors/d2', expect.anything())
  })

  it('предупреждение об услугах без врача — текст сервера', async () => {
    get.mockResolvedValueOnce(ok({ ...CARD, warning: 'Atenție: serviciile X rămân fără medic' }))
    render(<DoctorCardScreen dk="d2" />)
    expect(await screen.findByText(/rămân fără medic/)).toBeTruthy()
  })

  it('сегодня пусто — строка «nicio programare»', async () => {
    get.mockResolvedValueOnce(ok({ ...CARD, today: [] }))
    render(<DoctorCardScreen dk="d2" />)
    expect(await screen.findByText(/nicio programare/)).toBeTruthy()
  })

  it('сохранение: шлёт форму, шапка берёт свежие данные, плашка сервера', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockResolvedValueOnce(ok({ ...CARD, name: 'Dr. Doi Nou', work_from: 9, auto_color: false, color: '#112233' }, 'ok_med', 'Datele medicului au fost salvate'))
    render(<DoctorCardScreen dk="d2" />)
    await screen.findByText('Chirurgie')
    fireEvent.change(input('Nume'), { target: { value: 'Dr. Doi Nou' } })
    fireEvent.change(screen.getByLabelText('de la'), { target: { value: '9' } })
    fireEvent.click(screen.getByLabelText('automată'))
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/doctors/d2', {
      name: 'Dr. Doi Nou', spec: 'Chirurgie', room: '3', phone: '101', email: '',
      color: '#3B82F6', auto_color: false, work_from: 9, work_to: null, status: 'activ',
    })
    expect(screen.getByText('Dr. Doi Nou', { selector: 'b' })).toBeTruthy()
    expect((screen.getByLabelText('de la') as HTMLSelectElement).value).toBe('9')
  })

  it('сохранение: тёзка — 409 с текстом сервера', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'dup_med', text: 'Există deja un medic' }, 'c'))
    render(<DoctorCardScreen dk="d2" />)
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    expect(await screen.findByText('Există deja un medic')).toBeTruthy()
    expect(screen.getByRole('alert').getAttribute('data-kind')).toBe('err')
  })

  it('услуги: галочка и сохранение шлют список id, ответ подменяет галочки', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockResolvedValueOnce(ok({ services: [
      { id: 'consult', name: 'Consultație', checked: true, note: 'toți medicii' },
      { id: 'hygiene', name: 'Igienizare', checked: true, note: '2 medici' },
    ] }, 'ok_svc_med', 'Serviciile medicului au fost actualizate'))
    render(<DoctorCardScreen dk="d2" />)
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByLabelText(/Igienizare/))
    fireEvent.click(screen.getByRole('button', { name: 'Salvează serviciile' }))
    expect(await screen.findByText('Serviciile medicului au fost actualizate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/doctors/d2/services', { services: ['consult', 'hygiene'] })
    expect(screen.getByText('2 medici')).toBeTruthy()
  })

  it('услуги: последний врач услуги — 409 svc_empty с текстом', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'svc_empty', text: 'cel puțin un medic' }, 'c'))
    render(<DoctorCardScreen dk="d2" />)
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByLabelText(/Consultație/))
    fireEvent.click(screen.getByRole('button', { name: 'Salvează serviciile' }))
    expect(await screen.findByText('cel puțin un medic')).toBeTruthy()
  })

  it('фото: выбранный файл уезжает multipart, аватар получает адрес', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    postForm.mockResolvedValueOnce(ok({ photo: '/admin/doctor-photo/d2?v=new' }, 'ok_photo', 'Fotografia a fost salvată'))
    render(<DoctorCardScreen dk="d2" />)
    await screen.findByText('Chirurgie')
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'me.png', { type: 'image/png' })
    fireEvent.change(document.getElementById('docphoto-d2') as HTMLInputElement, { target: { files: [file] } })
    expect(screen.getByText('me.png')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Încarcă fotografia/ }))
    expect(await screen.findByText('Fotografia a fost salvată')).toBeTruthy()
    const [path, form] = postForm.mock.calls[0] as [string, FormData]
    expect(path).toBe('/doctors/d2/photo')
    expect((form.get('file') as File).name).toBe('me.png')
    expect(document.querySelector('.avatar img')?.getAttribute('src')).toBe('/admin/doctor-photo/d2?v=new')
    expect(screen.getByRole('button', { name: /Șterge fotografia/ })).toBeTruthy()
  })

  it('фото: удаление после подтверждения', async () => {
    get.mockResolvedValueOnce(ok({ ...CARD, photo: '/admin/doctor-photo/d2?v=old' }))
    post.mockResolvedValueOnce(ok({ photo: '' }, 'ok_med', 'Datele medicului au fost salvate'))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    render(<DoctorCardScreen dk="d2" />)
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: /Șterge fotografia/ }))
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/doctors/d2/photo/delete', {})
    expect(document.querySelector('.avatar img')).toBeNull()
  })

  it('врач не найден: своя фраза и путь на старую страницу', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 'nf'))
    render(<DoctorCardScreen dk="d9" />)
    expect(await screen.findByText(/Medicul nu există/)).toBeTruthy()
    expect((screen.getByRole('link', { name: 'Varianta clasică' }) as HTMLAnchorElement).getAttribute('href')).toContain('?ui=legacy')
  })

  it('401 при сохранении — на вход', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    render(<DoctorCardScreen dk="d2" navigate={navigate} />)
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})
