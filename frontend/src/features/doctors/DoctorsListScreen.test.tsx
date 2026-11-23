import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { DoctorsList } from './doctors'
import type { GdocList } from './gdoc'
import { GDOC_LIST_WORDS } from '../../test/gdocFixture'
import { openScreen } from '../../test/openScreen'
import { DoctorsListScreen, loadDoctorsList } from './DoctorsListScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, gget, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), gget: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
/* блок календарей врачей загрузчик просит своим запросом рядом со списком: у него своя очередь
   ответов, чтобы очередь списка, профиля и перечитывания осталась прежней */
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  const route = (path: string, ...rest: unknown[]) => (path === '/gdoc' ? gget : get)(path, ...rest)
  return { ...real, api: { get: route, post, postForm }, loginUrl: () => '/admin/login?next=x' }
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

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/medici', '/admin/medici', <DoctorsListScreen {...(navigate ? { navigate } : {})} />,
  loadDoctorsList, navigate)

beforeEach(() => {
  gget.mockResolvedValue(ok(null))
})

afterEach(() => {
  cleanup()
  get.mockReset()
  gget.mockReset()
  post.mockReset()
})

describe('DoctorsListScreen', () => {
  it('загрузка: форма добавления занята', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    open()
    expect(document.querySelector('section')?.getAttribute('aria-busy')).toBe('true')
    expect((screen.getByLabelText('Nume și prenume') as HTMLInputElement).disabled).toBe(true)
  })

  it('успех (08.10): карточки, плашки состояний с сервера, архивный приглушён в той же сетке', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    open()
    expect(await screen.findByText('Dr. Activ Doi')).toBeTruthy()
    expect(document.querySelector('.sub')?.textContent).toBe('1 activi · statistici pe ultimele 30 de zile')
    const card = (dk: string) => document.querySelector(`.dp-doc[data-dk="${dk}"]`) as HTMLElement
    expect(card('d2').querySelector('.chip')?.className).toContain('dbadge activ')
    expect(card('d1').querySelector('.chip')?.className).toContain('dbadge arhivat')
    expect(card('d1').className).toContain('off')
    expect(screen.queryByText('Arhivă')).toBeNull()
    expect(screen.getByText('L–V 9:00–17:00')).toBeTruthy()
    expect(screen.getByText('Programul clinicii')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    const link = screen.getByText('Dr. Activ Doi').closest('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/admin/doctor-card/d2')
    expect(card('d2').querySelector('.dp-doc-lnk')?.getAttribute('href')).toBe('/admin/doctor/d2')
    expect(document.querySelector('img')?.getAttribute('src')).toBe('/admin/doctor-photo/d1?v=x')
    expect((card('d2').querySelector('.dp-ring') as HTMLElement).style.borderColor).toBe('rgb(59, 130, 246)')
    expect(screen.queryByText(/aceeași culoare/)).toBeNull()
    /* кнопка добавления заперта, пока имя пустое */
    expect((screen.getByRole('button', { name: 'Adaugă medic' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('состояние из карточки: профиль читается целиком и записывается с новым состоянием, список перечитывается', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    get.mockResolvedValueOnce(ok({ name: 'Dr. Activ Doi', spec: 'Chirurgie', room: '3', phone: '101', email: 'a@b.md',
      color: '#3B82F6', auto_color: false, work_from: 9, work_to: 17, status: 'activ' }))
    post.mockResolvedValueOnce(ok(undefined, 'ok_med', 'Datele medicului au fost salvate'))
    get.mockResolvedValueOnce(ok({ ...LIST, doctors: LIST.doctors.map((d) => (d.id === 'd2' ? { ...d, status: 'concediu' } : d)) }))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.change(screen.getByLabelText('Status: Dr. Activ Doi'), { target: { value: 'concediu' } })
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/doctors/d2', expect.objectContaining({ status: 'concediu', name: 'Dr. Activ Doi', phone: '101', email: 'a@b.md' }))
    await waitFor(() => expect(document.querySelector('.dp-doc[data-dk="d2"] .chip')?.textContent).toBe('În concediu'))
  })

  it('пусто: ни одного врача — подсказка, форма открыта', async () => {
    get.mockResolvedValueOnce(ok({ ...LIST, doctors: [] }))
    open()
    expect(await screen.findByText(/Niciun medic/)).toBeTruthy()
    expect((screen.getByLabelText('Nume și prenume') as HTMLInputElement).disabled).toBe(false)
  })

  it('добавление: шлёт имя и специализацию, уходит в фишу нового с плашкой сервера', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    post.mockResolvedValueOnce(ok({ id: 'd5' }, 'new_med', 'Medic adăugat'))
    const navigate = vi.fn()
    const { router } = open(navigate)
    await screen.findByText('Dr. Activ Doi')
    fireEvent.change(screen.getByLabelText('Nume și prenume'), { target: { value: 'Dr. Cinci' } })
    fireEvent.change(screen.getByLabelText('Specializare'), { target: { value: 'Orto' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adaugă medic' }))
    /* B4: в фишу нового — ПЕРЕХОДОМ (плашку несёт адрес); `navigate` экрана — входу */
    await waitFor(() => expect(router.state.location.pathname + router.state.location.search)
      .toBe('/admin/doctor-card/d5?msg=new_med'))
    expect(navigate).not.toHaveBeenCalled()
    expect(post).toHaveBeenCalledWith('/doctors', { name: 'Dr. Cinci', spec: 'Orto' })
  })

  it('добавление: тёзка — текст сервера в плашке, форма остаётся', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'dup_med', text: 'Există deja un medic' }, 'c'))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.change(screen.getByLabelText('Nume și prenume'), { target: { value: 'Dr. Activ Doi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adaugă medic' }))
    expect(await screen.findByText('Există deja un medic')).toBeTruthy()
    expect((screen.getByLabelText('Nume și prenume') as HTMLInputElement).disabled).toBe(false)
  })

  it('одинаковые цвета: подсказка и сброс перечитывают список', async () => {
    get.mockResolvedValueOnce(ok({ ...LIST, same_color: true }))
    post.mockResolvedValueOnce(ok(undefined, 'ok_med', 'Datele medicului au fost salvate'))
    get.mockResolvedValueOnce(ok(LIST))
    open()
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
    open()
    fireEvent.click(await screen.findByRole('button', { name: /Reîncearcă/ }))
    expect(await screen.findByText('Dr. Activ Doi')).toBeTruthy()
  })

  it('401: на вход, ничего не рисует', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    open(navigate)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
    expect(screen.queryByLabelText('Nume și prenume')).toBeNull()
  })
})

/* ---- полоса «Calendarele medicilor în Google» и плашки врачей: слова и выбор — сервера ---- */

const WARN_I = 'Evenimentele vor arăta inițialele pacientului și numărul fișei.'
const WARN_N = 'Evenimentele vor arăta numele pacientului și serviciul — date despre sănătate.'
const GDOC: GdocList = {
  doctors: {
    d2: { state: 'on', account: 'medic@gmail.com', why: null },
    d1: { state: 'off', account: '', why: null },
  },
  level: {
    code: 'time', can_set: true, lock: '',
    choices: [
      { code: 'time', label: 'Doar ora', hint: 'Fără numele pacientului', warn: '', sample: 'Programare · Cabinet 1' },
      { code: 'initials', label: 'Inițiale', hint: 'Inițialele și numărul fișei', warn: WARN_I,
        sample: 'M.L. · Fișa 124 · Cabinet 1' },
      { code: 'name', label: 'Nume și serviciu', hint: 'Numele întreg și serviciul', warn: WARN_N,
        sample: 'Maria Lungu · Tratament carie · Cabinet 1' },
    ],
  },
  premium: null,
  words: GDOC_LIST_WORDS,
}
const strip = () => document.querySelector('.gdl') as HTMLElement | null
const radio = (name: string) => screen.getByRole('radio', { name: new RegExp(`^${name}`) })
const dlg = () => document.querySelector('dialog.gdl-dlg') as HTMLDialogElement | null

describe('DoctorsListScreen › Google', () => {
  it('блока нет (сервер прислал null) — ни полосы, ни плашек', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    open()
    await screen.findByText('Dr. Activ Doi')
    expect(gget).toHaveBeenCalledWith('/gdoc', expect.anything())
    expect(strip()).toBeNull()
    expect(document.querySelector('.gd-chip')).toBeNull()
  })

  it('полоса тем же кадром, что список: три положения, текущее нажато, образец события; плашки врачей', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok(GDOC))
    open()
    await screen.findByText('Dr. Activ Doi')
    expect(strip()?.textContent).toContain('Calendarele medicilor în Google')
    expect(screen.getByText(/Conectați: 1 din 2 medici/)).toBeTruthy()
    expect(radio('Doar ora').getAttribute('aria-checked')).toBe('true')
    expect(radio('Inițiale').getAttribute('aria-checked')).toBe('false')
    expect(screen.getByText('Programare · Cabinet 1')).toBeTruthy()
    expect(screen.getByText('La schimbare calendarele se rescriu singure, în cel mult 5 minute.')).toBeTruthy()
    const chip = (dk: string) => document.querySelector(`.dp-doc[data-dk="${dk}"] .gd-chip`)
    expect(chip('d2')?.textContent?.trim()).toBe('Google conectat')
    expect(chip('d2')?.className).toContain('ok')
    expect(chip('d1')?.textContent?.trim()).toBe('Google neconectat')
    expect(chip('d1')?.className).toContain('mute')
  })

  it('уровень без данных пациента ставится сразу, без окна; ответ приносит новый выбор', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok({ ...GDOC, level: { ...GDOC.level, code: 'initials' } }))
    post.mockResolvedValueOnce(ok({ level: { ...GDOC.level, code: 'time' } }, 'gd_level_ok',
      'Nivelul s-a schimbat: calendarele medicilor se rescriu singure, în cel mult 5 minute'))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.click(radio('Doar ora'))
    expect(await screen.findByText(/^Nivelul s-a schimbat/)).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/gdoc/level', { level: 'time', ack: false })
    expect(dlg()).toBeNull()
    expect(radio('Doar ora').getAttribute('aria-checked')).toBe('true')
  })

  it('уровень с именем пациента — окно: без «Am înțeles» «Salvează» заперта; с галочкой уходит ack', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok(GDOC))
    post.mockResolvedValueOnce(ok({ level: { ...GDOC.level, code: 'name' } }, 'gd_level_ok', 'Nivelul s-a schimbat'))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.click(radio('Nume și serviciu'))
    expect(dlg()?.open).toBe(true)
    expect(screen.getByText(WARN_N)).toBeTruthy()
    const save = screen.getByRole('button', { name: 'Alege „Nume și serviciu”' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText(GDOC_LIST_WORDS.dlg_ack))
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gdoc/level', { level: 'name', ack: true }))
    await waitFor(() => expect(dlg()).toBeNull())
    expect(radio('Nume și serviciu').getAttribute('aria-checked')).toBe('true')
  })

  it('инициалы — тоже через окно; «Renunță» ничего не шлёт и выбор прежний', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok(GDOC))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.click(radio('Inițiale'))
    expect(screen.getByText(WARN_I)).toBeTruthy()
    fireEvent.click(dlg()!.querySelector('.rg-dlg-f .rc-btn') as HTMLButtonElement)
    await waitFor(() => expect(dlg()).toBeNull())
    expect(post).not.toHaveBeenCalled()
    expect(radio('Doar ora').getAttribute('aria-checked')).toBe('true')
  })

  it('отказ сервера (нет галочки) — слова сервера, окно остаётся', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok(GDOC))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'gd_level_ack', text: 'Bifați „Am înțeles”',
      field: 'ack' }, 'v'))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.click(radio('Nume și serviciu'))
    fireEvent.click(screen.getByLabelText(GDOC_LIST_WORDS.dlg_ack))
    fireEvent.click(screen.getByRole('button', { name: 'Alege „Nume și serviciu”' }))
    expect(await screen.findByText('Bifați „Am înțeles”')).toBeTruthy()
    expect(dlg()?.open).toBe(true)
  })

  it('менять нельзя (регистратура): положения выключены, причина сервера', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok({ ...GDOC, level: { ...GDOC.level, can_set: false, lock: 'Schimbă doar directorul.' } }))
    open()
    await screen.findByText('Dr. Activ Doi')
    expect(screen.getByText('Schimbă doar directorul.')).toBeTruthy()
    expect((radio('Inițiale') as HTMLButtonElement).disabled).toBe(true)
    expect((radio('Nume și serviciu') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(radio('Nume și serviciu'))
    expect(dlg()).toBeNull()
  })

  it('нет Premium: одна строка с путём к оплате вместо выбора, плашек нет', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    const why = { code: 'gd_premium', tone: 'warn', text: 'Calendarul medicului în Google face parte din DentPilot Premium', detail: '' }
    gget.mockResolvedValueOnce(ok({ ...GDOC, premium: { href: '/admin/license', label: 'Setări › Licența' },
      doctors: { d2: { state: 'premium', account: '', why }, d1: { state: 'premium', account: '', why } } }))
    open()
    await screen.findByText('Dr. Activ Doi')
    expect(screen.getByText(GDOC_LIST_WORDS.premium)).toBeTruthy()
    expect(screen.getByText(/implicit doar ora/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Setări › Licența ›' }).getAttribute('href')).toBe('/admin/license')
    expect(screen.queryByRole('radiogroup')).toBeNull()
    expect(document.querySelector('.gd-chip')).toBeNull()
  })

  it('смена состояния врача перечитывает список и не теряет полосу', async () => {
    get.mockResolvedValueOnce(ok(LIST))
    gget.mockResolvedValueOnce(ok(GDOC))
    get.mockResolvedValueOnce(ok({ name: 'Dr. Activ Doi', spec: 'Chirurgie', room: '3', phone: '101', email: '',
      color: '#3B82F6', auto_color: false, work_from: 9, work_to: 17, status: 'activ' }))
    post.mockResolvedValueOnce(ok(undefined, 'ok_med', 'Datele medicului au fost salvate'))
    get.mockResolvedValueOnce(ok(LIST))
    open()
    await screen.findByText('Dr. Activ Doi')
    fireEvent.change(screen.getByLabelText('Status: Dr. Activ Doi'), { target: { value: 'concediu' } })
    expect(await screen.findByText('Datele medicului au fost salvate')).toBeTruthy()
    expect(strip()).toBeTruthy()
    expect(document.querySelector('.dp-doc[data-dk="d2"] .gd-chip')?.textContent?.trim()).toBe('Google conectat')
    expect(gget).toHaveBeenCalledTimes(1)
  })
})
