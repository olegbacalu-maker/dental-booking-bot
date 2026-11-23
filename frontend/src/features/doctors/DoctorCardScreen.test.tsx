import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { DoctorCard } from './doctors'
import type { GdocView } from './gdoc'
import { GDOC_WORDS } from '../../test/gdocFixture'
import { openScreen } from '../../test/openScreen'
import { DoctorCardScreen, loadDoctorCard } from './DoctorCardScreen'

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
  actions: {
    confirmed: [
      { to: 'waiting', cls: 'b-waiting', label: 'A venit', confirm: '' },
      { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' },
    ],
    done: [{ to: 'confirmed', cls: 'b-reopen', label: 'Redeschide',
             confirm: 'Redeschideți programarea (înapoi la «confirmată»)?' }],
  },
  note_actions: {
    confirmed: [{ to: 'cancelled', cls: 'b-cancel', label: 'Șterge', confirm: '' }],
    cancelled: [{ to: 'confirmed', cls: 'b-reopen', label: 'Restabilește',
                  confirm: 'Restabiliți notița?' }],
  },
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

const open = (dk: string, navigate?: (url: string) => void) => openScreen(
  '/admin/doctor-card/:dk', `/admin/doctor-card/${dk}`,
  <DoctorCardScreen dk={dk} {...(navigate ? { navigate } : {})} />, loadDoctorCard, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  postForm.mockReset()
})

describe('DoctorCardScreen', () => {
  it('успех: шапка, поля формы, неделя, сегодня, услуги, цифры', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    open('d2')
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
    open('d2')
    expect(await screen.findByText(/rămân fără medic/)).toBeTruthy()
  })

  it('сегодня пусто — строка «nicio programare»', async () => {
    get.mockResolvedValueOnce(ok({ ...CARD, today: [] }))
    open('d2')
    expect(await screen.findByText(/nicio programare/)).toBeTruthy()
  })

  it('сохранение: шлёт форму, шапка берёт свежие данные, плашка сервера', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockResolvedValueOnce(ok({ ...CARD, name: 'Dr. Doi Nou', work_from: 9, auto_color: false, color: '#112233' }, 'ok_med', 'Datele medicului au fost salvate'))
    open('d2')
    await screen.findByText('Chirurgie')
    fireEvent.change(input('Nume'), { target: { value: 'Dr. Doi Nou' } })
    fireEvent.change(screen.getByLabelText('de la'), { target: { value: '9' } })
    fireEvent.click(screen.getByLabelText('automată'))
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/doctors/d2', {
      name: 'Dr. Doi Nou', spec: 'Chirurgie', room: '3', rooms: [{ name: '3' }], phone: '101', email: '',
      color: '#3B82F6', auto_color: false, work_from: 9, work_to: null, status: 'activ',
    })
    expect(screen.getByText('Dr. Doi Nou', { selector: 'b' })).toBeTruthy()
    expect((screen.getByLabelText('de la') as HTMLSelectElement).value).toBe('9')
  })

  it('кабинеты: второй добавляют, порядок меняют — уходит список имён, первый — основной', async () => {
    get.mockResolvedValueOnce(ok({ ...CARD, rooms: [{ id: 'r-3', name: '3' }], rooms_all: [{ id: 'r-3', name: '3' }], rooms_max: 3 }))
    post.mockResolvedValueOnce(ok(CARD, 'ok_med', 'Datele medicului au fost salvate'))
    open('d2')
    await screen.findByText('Chirurgie')
    expect(screen.queryByRole('button', { name: /Mută mai sus/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Adaugă cabinet' }))
    fireEvent.change(input('Cabinet 2'), { target: { value: 'Chirurgie 2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Mută mai sus: Chirurgie 2' }))
    fireEvent.click(screen.getByRole('button', { name: 'Adaugă cabinet' }))
    expect(screen.queryByRole('button', { name: 'Adaugă cabinet' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    await screen.findByText('Datele medicului au fost salvate')
    expect(post.mock.calls[0]?.[1]).toMatchObject({
      room: 'Chirurgie 2', rooms: [{ name: 'Chirurgie 2' }, { name: '3' }],
    })
  })

  it('сохранение: тёзка — 409 с текстом сервера', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'dup_med', text: 'Există deja un medic' }, 'c'))
    open('d2')
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
    open('d2')
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
    open('d2')
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByLabelText(/Consultație/))
    fireEvent.click(screen.getByRole('button', { name: 'Salvează serviciile' }))
    expect(await screen.findByText('cel puțin un medic')).toBeTruthy()
  })

  it('фото: выбранный файл уезжает multipart, аватар получает адрес', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    postForm.mockResolvedValueOnce(ok({ photo: '/admin/doctor-photo/d2?v=new' }, 'ok_photo', 'Fotografia a fost salvată'))
    open('d2')
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
    open('d2')
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: /Șterge fotografia/ }))
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/doctors/d2/photo/delete', {})
    expect(document.querySelector('.avatar img')).toBeNull()
  })

  it('врач не найден: своя фраза и повтор, без пути на старую страницу (её нет с 13.10)', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 'nf'))
    open('d9')
    expect(await screen.findByText(/Medicul nu există/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Reîncearcă/ })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Varianta clasică' })).toBeNull()
  })

  /* ---- C14+: кнопки исхода в списке сегодняшнего дня ---- */

  it('кнопки берутся С СЕРВЕРА по состоянию строки, а у заметки — СВОИ', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    open('d2')
    await screen.findByText('Chirurgie')
    expect(screen.getByRole('button', { name: 'A venit' })).toBeTruthy()
    /* ⛔ Заметка стойки — не визит: ни «пришёл», ни «завершено» у неё нет. */
    expect(screen.getByRole('button', { name: 'Șterge' })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'A venit' })).toHaveLength(1)
  })

  it('исход уходит ЖУРНАЛЬНЫМ маршрутом и экран перечитывает себя', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockResolvedValueOnce(ok(undefined))
    get.mockResolvedValueOnce(ok({
      ...CARD,
      today: [{ ...CARD.today[0]!, status: 'waiting', status_label: 'în așteptare' },
              CARD.today[1]!],
    }))
    open('d2')
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: 'A venit' }))
    /* ⭐ Адрес чужой намеренно: менять состояние визита умеет одно место.
       `screen=med` просит НЕ присылать день журнала — у фиши своя модель. */
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/7/status?screen=med', { to: 'waiting' }))
    expect(await screen.findByText('în așteptare')).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('возврат закрытой записи спрашивают; отказ не шлёт ничего', async () => {
    get.mockResolvedValueOnce(ok({
      ...CARD,
      today: [{ ...CARD.today[0]!, status: 'done', status_label: 'finalizată' }],
    }))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    open('d2')
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: /Redeschide/ }))
    expect(post).not.toHaveBeenCalled()
  })

  it('401 при сохранении — на вход', async () => {
    get.mockResolvedValueOnce(ok(CARD))
    post.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open('d2', navigate)
    await screen.findByText('Chirurgie')
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})

/* ---- календарь врача в его Google: слова и состояние — сервера (`gcal_doctor.view`) ---- */

const OFF: GdocView = {
  state: 'off', account: '', calendar: null, last: null, pending: 0, why: null,
  level: { code: 'time', label: 'doar ora, fără numele pacientului' },
  notice: 'Programările pleacă de pe acest calculator direct în Google.',
  privacy: { href: 'https://dentpilot.md/privacy.html#google', label: 'dentpilot.md/privacy.html#google' },
  premium: null, waiting: false, remote: null,
  can: { connect: true, check: false, disconnect: false }, words: GDOC_WORDS,
}
const WAIT: GdocView = { ...OFF, state: 'waiting', waiting: true }
const ON: GdocView = {
  ...OFF, state: 'on', account: 'medic@gmail.com',
  calendar: { id: 'c1', name: 'DentPilot · Clinica Test · Dr. Activ Doi' },
  last: { at: '2026-11-23T12:20:00Z', when: '23.11.2026 14:20' },
  can: { connect: false, check: true, disconnect: true },
}
const block = () => document.querySelector('.gd') as HTMLElement | null
const withG = (g: GdocView | null) => ok({ ...CARD, google: g })
const buttons = () => [...(block()?.querySelectorAll('button') ?? [])].map((b) => b.textContent?.trim())

describe('DoctorCardScreen › Google', () => {
  it('блока нет, если сервер его не прислал', async () => {
    get.mockResolvedValueOnce(withG(null))
    open('d2')
    await screen.findByText('Chirurgie')
    expect(block()).toBeNull()
  })

  it('не подключён: уведомление и политика; «Conectează» открывает браузер Windows и ждёт', async () => {
    get.mockResolvedValueOnce(withG(OFF))
    post.mockResolvedValueOnce(ok({ view: WAIT, url: 'https://accounts.google.com/o?x=1' }, 'gd_url',
      'Pagina Google se deschide în browser'))
    const win = vi.spyOn(window, 'open').mockReturnValue(null)
    open('d2')
    expect(await screen.findByText(/pleacă de pe acest calculator/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'dentpilot.md/privacy.html#google' }).getAttribute('href'))
      .toBe('https://dentpilot.md/privacy.html#google')
    fireEvent.click(screen.getByRole('button', { name: 'Conectează Google' }))
    expect(await screen.findByText('Așteptăm răspunsul Google…')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/gdoc/d2/connect', {})
    expect(win).toHaveBeenCalledWith('https://accounts.google.com/o?x=1', '_blank', 'noopener')
    expect(screen.getByText('Pagina Google se deschide în browser')).toBeTruthy()
    expect(block()?.getAttribute('data-gd')).toBe('waiting')
  })

  it('ожидание: опрос раз в 3 с и при возврате в окно; вход закончился — подключён', async () => {
    get.mockResolvedValueOnce(withG(WAIT))
    get.mockResolvedValueOnce(ok(WAIT))
    get.mockResolvedValueOnce(ok(ON))
    open('d2')
    await screen.findByText('Așteptăm răspunsul Google…')
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      vi.advanceTimersByTime(3000)
      await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
      expect(get).toHaveBeenLastCalledWith('/gdoc/d2', {})
    } finally {
      vi.useRealTimers()
    }
    fireEvent.focus(window)
    expect(await screen.findByText('medic@gmail.com')).toBeTruthy()
    expect(screen.getByText('Ultima actualizare: 23.11.2026 14:20 — totul e la zi.')).toBeTruthy()
    const lvl = screen.getByRole('link', { name: /Ce vede medicul: doar ora, fără numele pacientului/ })
    expect(lvl.getAttribute('href')).toBe('/admin/medici')
  })

  it('опрос, обогнанный командой, отбрасывается: «Renunță» не возвращается к ожиданию', async () => {
    get.mockResolvedValueOnce(withG(WAIT))
    let late: (v: unknown) => void = () => {}
    get.mockReturnValueOnce(new Promise((r) => { late = r }))
    post.mockResolvedValueOnce(ok({ view: OFF }, 'gd_cancel', 'Conectarea a fost oprită'))
    open('d2')
    await screen.findByText('Așteptăm răspunsul Google…')
    fireEvent.focus(window)
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByRole('button', { name: 'Renunță' }))
    expect(await screen.findByText('Conectarea a fost oprită')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/gdoc/d2/cancel', {})
    late(ok(WAIT))
    await new Promise((r) => setTimeout(r, 0))
    expect(block()?.getAttribute('data-gd')).toBe('off')
    expect(screen.queryByText('Așteptăm răspunsul Google…')).toBeNull()
  })

  it('подключён: «Sincronizează acum» — слова ответа и сколько ещё в пути; «Deconectează» спрашивает', async () => {
    get.mockResolvedValueOnce(withG(ON))
    post.mockResolvedValueOnce(ok({ view: { ...ON, pending: 3, words: { ...GDOC_WORDS, pending: 'încă 3 programări în drum.' } } },
      'gd_checked', 'Calendarul medicului este actualizat'))
    post.mockResolvedValueOnce(ok({ view: OFF }, 'gd_off', 'Calendarul medicului a fost șters din Google'))
    const conf = vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    open('d2')
    expect(await screen.findByText('„DentPilot · Clinica Test · Dr. Activ Doi”')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizează acum' }))
    expect(await screen.findByText('Calendarul medicului este actualizat')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/gdoc/d2/check', {})
    expect(screen.getByText('Ultima actualizare: 23.11.2026 14:20 — încă 3 programări în drum.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Deconectează' }))
    expect(await screen.findByText('Calendarul medicului a fost șters din Google')).toBeTruthy()
    expect(conf).toHaveBeenCalledWith(GDOC_WORDS.disconnect_ask)
    expect(post).toHaveBeenLastCalledWith('/gdoc/d2/disconnect', {})
    expect(screen.getByRole('button', { name: 'Conectează Google' })).toBeTruthy()
  })

  it('«Deconectează» без согласия ничего не шлёт', async () => {
    get.mockResolvedValueOnce(withG(ON))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    open('d2')
    await screen.findByText('medic@gmail.com')
    fireEvent.click(screen.getByRole('button', { name: 'Deconectează' }))
    expect(post).not.toHaveBeenCalled()
  })

  it('отказ команды несёт вид: блок встаёт по нему, слова отказа — в плашке', async () => {
    get.mockResolvedValueOnce(withG(OFF))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'gd_on', text: 'Medicul este deja conectat',
      data: { view: ON } }, 'c'))
    open('d2')
    await screen.findByText(/pleacă de pe acest calculator/)
    fireEvent.click(screen.getByRole('button', { name: 'Conectează Google' }))
    expect(await screen.findByText('Medicul este deja conectat')).toBeTruthy()
    expect(screen.getByText('medic@gmail.com')).toBeTruthy()
  })

  it('проход не удался: строка ошибки вместо уровня, кнопки те же', async () => {
    get.mockResolvedValueOnce(withG({ ...ON, why: { code: 'gd_offline', tone: 'warn',
      text: 'Ultima actualizare nu a reușit', detail: 'Google nu a răspuns.', at: '2026-11-23T12:30:00Z',
      when: '23.11.2026 14:30' } }))
    open('d2')
    expect(await screen.findByText('Ultima actualizare nu a reușit')).toBeTruthy()
    expect(block()?.querySelector('.gd-status')?.textContent)
      .toBe('Ultima actualizare nu a reușit (23.11.2026 14:30) Google nu a răspuns. Ultima reușită: 23.11.2026 14:20.')
    expect(screen.queryByRole('link', { name: /Ce vede medicul/ })).toBeNull()
    expect(buttons()).toEqual(['Sincronizează acum', 'Deconectează'])
    expect(block()?.querySelector('.gl-mark')?.className).toContain('warn')
  })

  it('нет Premium: строка и путь к оплате, кнопок нет', async () => {
    get.mockResolvedValueOnce(withG({ ...OFF, state: 'premium', premium: { href: '/admin/license', label: 'Setări › Licența' },
      can: { connect: false, check: false, disconnect: false },
      why: { code: 'gd_premium', tone: 'plus', text: 'Calendarul medicului în Google face parte din DentPilot Premium', detail: '' } }))
    open('d2')
    expect(await screen.findByText('Calendarul medicului în Google face parte din DentPilot Premium.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Setări › Licența ›' }).getAttribute('href')).toBe('/admin/license')
    expect(buttons()).toEqual([])
  })

  it('пауза: связь приглушена, путь к оплате, только «Deconectează»', async () => {
    get.mockResolvedValueOnce(withG({ ...ON, state: 'paused', premium: { href: '/admin/license', label: 'Setări › Licența' },
      can: { connect: false, check: false, disconnect: true },
      why: { code: 'gd_paused', tone: 'plus', text: 'Actualizarea calendarului este oprită — face parte din DentPilot Premium',
             detail: 'Legătura rămâne.' } }))
    open('d2')
    expect(await screen.findByText(/Actualizarea calendarului este oprită/)).toBeTruthy()
    expect(block()?.querySelector('.gd-lines')?.className).toContain('gl-dim')
    expect(block()?.querySelector('.gl-mark')?.className).toContain('plus')
    expect(screen.getByRole('link', { name: 'Setări › Licența ›' })).toBeTruthy()
    expect(buttons()).toEqual(['Deconectează'])
  })

  it('связь надо переделать: «Conectează din nou» и «Deconectează»', async () => {
    get.mockResolvedValueOnce(withG({ ...ON, state: 'reconnect', can: { connect: true, check: false, disconnect: true },
      why: { code: 'gd_dead', tone: 'err', text: 'Legătura cu Google trebuie refăcută', detail: 'Accesul a fost retras.' } }))
    open('d2')
    expect(await screen.findByText('Legătura cu Google trebuie refăcută')).toBeTruthy()
    expect(buttons()).toEqual(['Conectează din nou', 'Deconectează'])
  })

  it('режим чтения: серый замок, без пути к оплате Premium, только «Deconectează»', async () => {
    get.mockResolvedValueOnce(withG({ ...ON, state: 'readonly', can: { connect: false, check: false, disconnect: true },
      why: { code: 'gd_readonly', tone: 'plus', text: 'Actualizarea calendarului este oprită cât programul este în regim de citire',
             detail: 'După plata abonamentului se actualizează din nou singur.' } }))
    open('d2')
    expect(await screen.findByText(/regim de citire/)).toBeTruthy()
    expect(block()?.querySelector('.gl-mark')?.className).toContain('plus')
    expect(screen.queryByRole('link', { name: /Licența/ })).toBeNull()
    expect(buttons()).toEqual(['Deconectează'])
  })

  it('чужой компьютер: «Conectează aici»', async () => {
    get.mockResolvedValueOnce(withG({ ...ON, state: 'foreign', can: { connect: true, check: false, disconnect: true },
      why: { code: 'gd_foreign', tone: 'err', text: 'Medicul a fost conectat pe alt calculator', detail: 'Aici nu se actualizează.' } }))
    open('d2')
    expect(await screen.findByText('Medicul a fost conectat pe alt calculator')).toBeTruthy()
    expect(buttons()).toEqual(['Conectează aici', 'Deconectează'])
  })

  it('второй ПК: «Conectează» видна выключенной и строка сервера', async () => {
    get.mockResolvedValueOnce(withG({ ...OFF, can: { connect: false, check: false, disconnect: false },
      remote: 'Medicul se conectează doar de pe calculatorul pe care rulează programul.' }))
    open('d2')
    expect(await screen.findByText(/doar de pe calculatorul pe care rulează programul/)).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Conectează Google' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
