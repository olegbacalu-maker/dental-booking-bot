import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { PatientsPage, PatientsSummary } from './patients'
import { filtersFromParams, filtersToQuery } from './patients'
import { nativeClick } from '../../test/nativeClick'
import { openScreen } from '../../test/openScreen'
import { filtersOf, loadPatientsSearch, PatientsSearchScreen } from './PatientsSearchScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const SUMMARY: PatientsSummary = {
  tiles: [
    { icon: 'users', tone: 'g', value: '14', foot: "<span class='up'>+3</span> luna aceasta", href: '' },
    { icon: 'med', tone: 'b', value: '3', foot: 'la fel ca luna trecută', href: '' },
    { icon: 'cal', tone: 'v', value: '7', foot: '<span class=\'up\'>+7</span> față de luna trecută (0)', href: '/admin/stats' },
  ],
  doctors: ['Dr. Activ Doi', 'Dr. Activ Trei'],
  channels: [{ id: 'manual', label: 'recepție' }, { id: 'web', label: 'web' }],
  statuses: [
    { id: 'arhivat', label: 'Arhivat', cls: 'arh' },
    { id: 'atentie', label: 'Necesită atenție', cls: 'att' },
    { id: 'tratament', label: 'În tratament', cls: 'trt' },
    { id: 'inactiv', label: 'Inactiv', cls: 'off' },
    { id: 'activ', label: 'Activ', cls: 'act' },
  ],
  per: [10, 20, 50],
  clinic_doctors: ['Dr. Activ Doi', 'Dr. Activ Trei'],
}

const ROW = {
  id: 6, name: 'Avans Popescu', initials: 'AP', phone: '022220022', email: '', channel: 'manual',
  birth: '', age: null, doctor: 'Dr. Activ Doi', doctor_own: false, last: '14.09.2026', next: '',
  n_visits: 1, debt: -300, status: 'activ', archived: false,
}
const ROW2 = {
  id: 2, name: 'Dumitru Ganea', initials: 'DG', phone: '', email: 'dg@example.com', channel: 'manual',
  birth: '01.01.2003', age: 23, doctor: 'Dr. Activ Trei', doctor_own: true, last: '12.09.2026',
  next: '20.09 10:00', n_visits: 2, debt: 1200, status: 'atentie', archived: false,
}
const PAGE: PatientsPage = {
  rows: [ROW, ROW2], total: 14, page: 1, pages: 2, per: 10, sort: 'last', hidden_arh: 1, n_arh: 1,
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

/** Ответы по адресу: сводка — одна, страницы — по строке запроса. */
function serve(pages: Record<string, PatientsPage> = { '': PAGE }) {
  get.mockImplementation((path: string) => {
    if (path === '/patients/summary') return Promise.resolve(ok(SUMMARY))
    if (path.startsWith('/patients?') || path === '/patients') {
      const qs = path.slice('/patients'.length)
      const page = pages[qs]
      return page ? Promise.resolve(ok(page)) : Promise.reject(new Error(`no page for ${qs}`))
    }
    return Promise.reject(new Error(`unexpected ${path}`))
  })
}

function pageCalls(): string[] {
  return get.mock.calls.map((c) => c[0] as string).filter((p) => p !== '/patients/summary')
}
const summaryCalls = () => get.mock.calls.filter((c) => c[0] === '/patients/summary').length

/* Экран открывается маршрутом (B2.2/B2.3): отбор приходит из АДРЕСА. */
function open(url = '/admin/search', props: { navigate?: (u: string) => void; debounceMs?: number } = {}) {
  const { navigate, debounceMs = 0 } = props
  return openScreen('/admin/search', url,
    <PatientsSearchScreen debounceMs={debounceMs} {...(navigate ? { navigate } : {})} />,
    loadPatientsSearch, navigate)
}

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('filters', () => {
  it('из параметров узла и обратно в адрес — без значений по умолчанию', () => {
    const f = filtersFromParams({ q: 'balan', st: 'inactiv', per: '10', sort: 'zzz', page: '3' })
    expect(f).toEqual({ q: 'balan', med: '', st: 'inactiv', ch: '', dat: '', sort: 'last', page: 3, per: 10 })
    expect(filtersToQuery(f)).toBe('?q=balan&st=inactiv&per=10&page=3')
    expect(filtersToQuery(f, false)).toBe('?q=balan&st=inactiv&per=10')
    expect(filtersToQuery(filtersFromParams({}))).toBe('')
    expect(filtersFromParams({ per: '7', page: '0' })).toMatchObject({ per: 20, page: 1 })
  })

  it('из АДРЕСА — правилом сервера: повтор ключа — последний, q обрезан', () => {
    const f = filtersOf(new URLSearchParams('q=%20gan%20&st=activ&st=inactiv&page=2'))
    expect(f).toMatchObject({ q: 'gan', st: 'inactiv', page: 2 })
  })
})

describe('PatientsSearchScreen', () => {
  it('строки: имя, канал вместо e-mail, долг и аванс, статус словами сервера, врач с последнего визита', async () => {
    serve()
    open()
    expect(await screen.findByText('Avans Popescu')).toBeTruthy()
    expect(screen.getByText('recepție', { selector: 'small' })).toBeTruthy()
    expect(screen.getByText('dg@example.com')).toBeTruthy()
    expect(screen.getByText('avans 300').className).toBe('pl-badge act')
    expect(screen.getByText('1 200 MDL').className).toBe('pl-badge bad')
    expect(screen.getByText('Activ', { selector: 'span' }).className).toBe('pl-badge act')
    expect(screen.getByText('Necesită atenție', { selector: 'span' }).className).toBe('pl-badge att')
    expect(screen.getByText('Dr. Activ Doi', { selector: 'td span' }).className).toBe('dim')
    expect(screen.getByText('› 20.09 10:00')).toBeTruthy()
    expect(screen.getByTitle('Fără telefon')).toBeTruthy()
    expect(screen.getByText(/23 ani/)).toBeTruthy()
    expect(screen.getByText('Total pacienți').parentElement?.querySelector('b')?.textContent).toBe('14')
    expect(screen.getByText(/Afișare 1–10 din 14 pacienți/)).toBeTruthy()
    expect(screen.getByText('arată')).toBeTruthy()
    expect((screen.getByText('Exportă').closest('a') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/patients.xlsx')
    expect(screen.getByText('Ultima vizită').closest('a')?.querySelector('svg')).toBeTruthy()
    const opts = Array.from((screen.getByLabelText('Toți medicii') as HTMLSelectElement).options).map((o) => o.value)
    expect(opts).toEqual(['', '-', 'Dr. Activ Doi', 'Dr. Activ Trei'])
    expect(pageCalls()).toEqual(['/patients'])
  })

  it('поиск: буква ждёт паузу и уезжает параметром q, адрес страницы повторяет отбор', async () => {
    const found: PatientsPage = { ...PAGE, rows: [ROW2], total: 1, pages: 1, hidden_arh: 0 }
    serve({ '': PAGE, '?q=gan': found })
    const { router } = open()
    await screen.findByText('Avans Popescu')
    fireEvent.change(screen.getByLabelText('Caută pacient, telefon, e-mail…'), { target: { value: 'gan' } })
    expect(await screen.findByText(/Afișare 1–1 din 1 pacienți/)).toBeTruthy()
    expect(screen.queryByText('Avans Popescu')).toBeNull()
    expect(pageCalls()).toEqual(['/patients', '/patients?q=gan'])
    expect(router.state.location.search).toBe('?q=gan')
    expect(router.state.historyAction).toBe('REPLACE')
    expect(screen.getByText('Resetează')).toBeTruthy()
    fireEvent.click(screen.getByText('Resetează'))
    expect(await screen.findByText('Avans Popescu')).toBeTruthy()
    expect(router.state.location.search).toBe('')
    expect((screen.getByLabelText('Caută pacient, telefon, e-mail…') as HTMLInputElement).value).toBe('')
  })

  it('фильтр статуса и сортировка идут сразу, страница сбрасывается', async () => {
    serve({ '?page=2': { ...PAGE, page: 2 }, '?st=atentie': { ...PAGE, rows: [ROW2], total: 1, pages: 1 },
            '?st=atentie&sort=name': { ...PAGE, rows: [ROW2], total: 1, pages: 1, sort: 'name' } })
    const { router } = open('/admin/search?page=2')
    await screen.findByText('Avans Popescu')
    expect(pageCalls()).toEqual(['/patients?page=2'])
    fireEvent.change(screen.getByLabelText('Toate statusurile'), { target: { value: 'atentie' } })
    await waitFor(() => expect(pageCalls()).toContain('/patients?st=atentie'))
    fireEvent.click(screen.getByText('Pacient'))
    await waitFor(() => expect(pageCalls()).toContain('/patients?st=atentie&sort=name'))
    expect(router.state.location.search).toBe('?st=atentie&sort=name')
  })

  it('страницы: ссылки с адресом, размер страницы с сервера', async () => {
    serve({ '': PAGE, '?page=2': { ...PAGE, rows: [ROW2], page: 2 },
            '?per=50': { ...PAGE, rows: [ROW, ROW2], per: 50, pages: 1 } })
    open()
    await screen.findByText('Avans Popescu')
    const next = screen.getByText('›', { selector: 'a' }) as HTMLAnchorElement
    expect(next.getAttribute('href')).toBe('/admin/search?page=2')
    fireEvent.click(next)
    await waitFor(() => expect(pageCalls()).toContain('/patients?page=2'))
    expect(await screen.findByText(/Afișare 11–14 din 14/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('/ pagină'), { target: { value: '50' } })
    await waitFor(() => expect(pageCalls()).toContain('/patients?per=50'))
  })

  it('клик по строке: предпросмотр приходит куском сервера, Escape закрывает', async () => {
    serve()
    get.mockImplementationOnce((path: string) => (path === '/patients/summary' ? Promise.resolve(ok(SUMMARY)) : Promise.resolve(ok(PAGE))))
    const base = get.getMockImplementation()!
    get.mockImplementation((path: string) => (path === '/patients/6/peek'
      ? Promise.resolve(ok({ html: "<div class='pp-head'><b>Avans Popescu</b></div><a href='/admin/patient/6'>Editează fișa</a>" }))
      : base(path)))
    const { router } = open()
    fireEvent.click(await screen.findByText('Avans Popescu'))
    expect(await screen.findByText('Editează fișa')).toBeTruthy()
    expect(document.querySelector('aside')?.className).toBe('ppanel open')
    expect(document.getElementById('plr6')?.className).toBe('on')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(document.querySelector('aside')?.className).toBe('ppanel')
    expect(screen.queryByText('Editează fișa')).toBeNull()

    /* B4: ссылка в прозе предпросмотра — переход роутером, не документ (голой
       она перезагружала окно — «дёргание» поиск → фиша на канарейке 1.30.2). */
    fireEvent.click(screen.getByText('Avans Popescu'))
    const link = await screen.findByText('Editează fișa')
    let native = true
    await act(async () => { native = nativeClick(link) })
    expect(native).toBe(false)
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/patient/6'))
  })

  it('предпросмотр исчезнувшей фиши — своя фраза', async () => {
    serve()
    const base = get.getMockImplementation()!
    get.mockImplementation((path: string) => (path === '/patients/2/peek'
      ? Promise.reject(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 'nf'))
      : base(path)))
    open()
    await screen.findByText('Dumitru Ganea')
    fireEvent.click(document.querySelector('#plr2 button') as HTMLButtonElement)
    expect(await screen.findByText('Fișa nu mai există.')).toBeTruthy()
  })

  it('новая фиша: диалог шлёт поля и уводит по адресу сервера; отказ — словами', async () => {
    serve()
    const navigate = vi.fn()
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_pat', text: 'Lipsește numele', field: 'name' }, 'v'))
    post.mockResolvedValueOnce(ok({ id: 9, url: '/admin/patient/9?msg=new_pat' }, 'new_pat', 'Pacient adăugat'))
    const { router } = open('/admin/search', { navigate })
    await screen.findByText('Avans Popescu')
    fireEvent.click(screen.getByText('＋ Adaugă pacient'))
    const form = document.querySelector('dialog form') as HTMLFormElement
    fireEvent.submit(form)
    expect(await screen.findByText('Lipsește numele')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Nume și prenume'), { target: { value: 'Ion Nou' } })
    fireEvent.change(screen.getByLabelText('Telefon', { selector: 'dialog input' }), { target: { value: '060 111 222' } })
    fireEvent.change(screen.getByLabelText('Data nașterii', { selector: 'dialog input' }), { target: { value: '1990-05-06' } })
    fireEvent.change(screen.getByLabelText('Medic curant'), { target: { value: 'Dr. Activ Trei' } })
    fireEvent.submit(form)
    /* B4: новая фиша открывается ПЕРЕХОДОМ по адресу сервера (с ?msg= для
       плашки оболочки), а не документом — `navigate` экрана остаётся входу. */
    await waitFor(() => expect(router.state.location.pathname + router.state.location.search)
      .toBe('/admin/patient/9?msg=new_pat'))
    expect(navigate).not.toHaveBeenCalled()
    expect(post).toHaveBeenLastCalledWith('/patients', {
      name: 'Ion Nou', phone: '060 111 222', birth_date: '1990-05-06', email: '', primary_doctor: 'Dr. Activ Trei',
    })
  })

  it('«fără telefon» выключает и чистит поле телефона', async () => {
    serve()
    open()
    await screen.findByText('Avans Popescu')
    const phone = screen.getByLabelText('Telefon', { selector: 'dialog input' }) as HTMLInputElement
    fireEvent.change(phone, { target: { value: '069' } })
    fireEvent.click(screen.getByLabelText('fără telefon'))
    expect(phone.disabled).toBe(true)
    expect(phone.value).toBe('')
  })

  it('пустые виды: «Nimic găsit» при отборе, «Toți … în arhivă» без отбора', async () => {
    const empty: PatientsPage = { ...PAGE, rows: [], total: 0, pages: 1, hidden_arh: 0 }
    serve({ '': { ...empty, n_arh: 2 }, '?q=zz': { ...empty, n_arh: 2 } })
    open()
    expect(await screen.findByText('Toți pacienții sunt în arhivă')).toBeTruthy()
    expect(screen.getByText(/2 fișe arhivate/)).toBeTruthy()
    expect(screen.queryByText(/Afișare/)).toBeNull()
    fireEvent.change(screen.getByLabelText('Caută pacient, telefon, e-mail…'), { target: { value: 'zz' } })
    expect(await screen.findByText('Nimic găsit')).toBeTruthy()
  })

  it('401 при загрузке — уходим на вход, экран не рисуется', async () => {
    get.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open('/admin/search', { navigate })
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
    expect(document.querySelector('.pl-grid')).toBeNull()
  })

  it('движок молчит — плашка и повтор', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'down' }, 'n'))
    open()
    expect(await screen.findByText(/Programul nu răspunde/)).toBeTruthy()
    serve()
    fireEvent.click(screen.getByText('Reîncearcă'))
    expect(await screen.findByText('Avans Popescu')).toBeTruthy()
  })
  it('сводка — ОДИН раз на открытие: смена отбора тянет только страницу списка', async () => {
    serve({ '': PAGE, '?st=atentie': { ...PAGE, rows: [ROW2], total: 1, pages: 1 },
            '?st=atentie&sort=name': { ...PAGE, rows: [ROW2], total: 1, pages: 1, sort: 'name' } })
    open()
    await screen.findByText('Avans Popescu')
    fireEvent.change(screen.getByLabelText('Toate statusurile'), { target: { value: 'atentie' } })
    await waitFor(() => expect(pageCalls()).toContain('/patients?st=atentie'))
    fireEvent.click(screen.getByText('Pacient'))
    await waitFor(() => expect(pageCalls()).toContain('/patients?st=atentie&sort=name'))
    expect(summaryCalls()).toBe(1)
  })

  it('F5 на адресе отбора — тот же список: свежий роутер просит то же', async () => {
    serve({ '': PAGE, '?st=atentie': { ...PAGE, rows: [ROW2], total: 1, pages: 1 } })
    const { router } = open()
    await screen.findByText('Avans Popescu')
    fireEvent.change(screen.getByLabelText('Toate statusurile'), { target: { value: 'atentie' } })
    await screen.findByText(/Afișare 1–1 din 1 pacienți/)
    const last = pageCalls().at(-1)
    const at = router.state.location.pathname + router.state.location.search
    cleanup()
    get.mockClear()
    open(at)
    expect(await screen.findByText(/Afișare 1–1 din 1 pacienți/)).toBeTruthy()
    expect(pageCalls()).toEqual([last])
    expect((screen.getByLabelText('Toate statusurile') as HTMLSelectElement).value).toBe('atentie')
  })

  it('буква ждёт паузу: до неё адрес прежний, после — с q', async () => {
    serve({ '': PAGE, '?q=gan': { ...PAGE, rows: [ROW2], total: 1, pages: 1, hidden_arh: 0 } })
    const { router } = open('/admin/search', { debounceMs: 60 })
    await screen.findByText('Avans Popescu')
    fireEvent.change(screen.getByLabelText('Caută pacient, telefon, e-mail…'), { target: { value: 'gan' } })
    expect(router.state.location.search).toBe('')
    expect((screen.getByLabelText('Caută pacient, telefon, e-mail…') as HTMLInputElement).value).toBe('gan')
    await waitFor(() => expect(router.state.location.search).toBe('?q=gan'))
    expect(await screen.findByText(/Afișare 1–1 din 1 pacienți/)).toBeTruthy()
  })

  it('щелчок по сортировке за миг до паузы не теряет набранное', async () => {
    serve({ '': PAGE, '?q=gan&sort=name': { ...PAGE, rows: [ROW2], total: 1, pages: 1, sort: 'name' } })
    const { router } = open('/admin/search', { debounceMs: 10_000 })
    await screen.findByText('Avans Popescu')
    fireEvent.change(screen.getByLabelText('Caută pacient, telefon, e-mail…'), { target: { value: 'gan' } })
    fireEvent.click(screen.getByText('Pacient'))
    await waitFor(() => expect(router.state.location.search).toBe('?q=gan&sort=name'))
    await waitFor(() => expect(pageCalls()).toContain('/patients?q=gan&sort=name'))
  })

  it('страница за пределом: сервер схлопнул — адрес за ним, список по поправленному', async () => {
    serve({ '': PAGE, '?page=9': { ...PAGE, rows: [ROW2], page: 2 }, '?page=2': { ...PAGE, rows: [ROW2], page: 2 } })
    const { router } = open()
    await screen.findByText('Avans Popescu')
    await act(() => router.navigate('/admin/search?page=9', { replace: true }))
    await waitFor(() => expect(router.state.location.search).toBe('?page=2'))
    expect(await screen.findByText(/Afișare 11–/)).toBeTruthy()
  })

  it('отказ дочитки — плашка, и «занято» не висит', async () => {
    serve({ '': PAGE })
    open()
    await screen.findByText('Avans Popescu')
    fireEvent.change(screen.getByLabelText('Toate statusurile'), { target: { value: 'inactiv' } })
    expect(await screen.findByText(/Programul nu răspunde/)).toBeTruthy()
    expect(document.querySelector('section')?.getAttribute('aria-busy')).toBe('false')
  })
})
