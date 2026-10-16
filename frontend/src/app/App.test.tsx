import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, matchRoutes } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ShellModel } from '../layouts/shell'
import { nativeClick } from '../test/nativeClick'
import { ApiError } from '../types/api'
import { App, appHydration, appRoutes, docChanged, orderDoc, SCREENS, type MountNode } from './App'
import { ROUTES } from './routes'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

/* Документ нового адреса (B4) — подмена: сервера в проверках нет. */
const { fetchDoc } = vi.hoisted(() => ({ fetchDoc: vi.fn() }))
vi.mock('../services/doc', () => ({ fetchDoc }))

/* Уход документом (вход, «нет доступа») — подмена: jsdom переходов не умеет. */
const { leave } = vi.hoisted(() => ({ leave: vi.fn() }))
vi.mock('../hooks/useLoad', async (importOriginal) => ({
  ...await importOriginal<typeof import('../hooks/useLoad')>(),
  defaultNavigate: leave,
}))

/* Экран, который падает при отрисовке: ловушку ошибок иначе не проверить.
   FAQ выбран потому, что больше ни одна проверка этого файла его не открывает. */
vi.mock('../features/settings/FaqScreen', async (importOriginal) => ({
  ...await importOriginal<typeof import('../features/settings/FaqScreen')>(),
  FaqScreen: () => { throw new Error('FAQ a căzut') },
}))

const SHELL: ShellModel = {
  identity: null,
  clinic: { name: 'Clinica Test', mark: '', logo_topbar: '', logo: '' },
  runtime: { version: '9.9.9', tz: 'Europe/Chisinau' },
  entry: { pin: false, pin_max: 8, backdrop: '' },
  nav: {
    active: 'set',
    items: [{ key: 'set', href: '/admin/settings', icon: 'home', label: 'Setări' }],
    sync: [],
    foot_title: '',
  },
  signals: {
    license: { shown: false, html: '' },
    tamper: { shown: false, html: '' },
    split: { shown: false, html: '' },
    slot: { shown: false, html: '' },
    setup: { shown: false, html: '' },
    demo: { shown: false, html: '' },
  },
  frame: {
    title: 'Setări', sub: 'setări', crumbs: [], rail: false, update: '', msg: '',
    site: { href: 'https://dentpilot.md', mark: '<svg class="bcmark"></svg>' },
    feedback: { email: 'x@y.md', href: 'mailto:x@y.md' }, today: '2026-09-24',
  },
}

function node(screen: string, params: Record<string, string> = {}, shell: ShellModel | null = null): MountNode {
  return { screen, params, shell }
}

/** Окно, открытое на адресе: узел документа отдаётся роутеру готовым, как в main.tsx. */
function open(url: string, n: MountNode) {
  const router = createMemoryRouter(appRoutes(), { initialEntries: [url], hydrationData: appHydration(n) })
  return { router, ...render(<App router={router} />) }
}

/** Адрес-образец маршрута: каждый `:параметр` заменён числом. */
const sample = (path: string) => path.replace(/:[a-z_]+/g, '7')

/** Какой маршрут таблицы выиграл на адресе — самый глубокий в совпадении. */
function winner(url: string): string | undefined {
  return matchRoutes(appRoutes(), url)?.at(-1)?.route.path
}

/* Прокрутку после перехода ставит `ScrollRestoration`, а jsdom её не умеет —
   без подмены каждая проверка перехода печатала бы «Not implemented». */
beforeAll(() => { window.scrollTo = vi.fn() as unknown as typeof window.scrollTo })

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  fetchDoc.mockReset()
  leave.mockReset()
  vi.restoreAllMocks()
})

describe('таблица маршрутов', () => {
  it('у каждого маршрута есть экран, и лишних экранов нет', () => {
    expect(Object.keys(SCREENS).sort()).toEqual(ROUTES.map((r) => r.screen).sort())
  })

  it('каждый адрес карты попадает в СВОЙ маршрут, а не в соседний', () => {
    for (const r of ROUTES) expect(winner(sample(r.path)), r.path).toBe(r.path)
  })

  it('день врача и карточка врача — разные маршруты, хоть и отличаются одним словом', () => {
    expect(winner('/admin/doctor/ana')).toBe('/admin/doctor/:dk')
    expect(winner('/admin/doctor-card/ana')).toBe('/admin/doctor-card/:dk')
  })

  it('маршрут с загрузчиком несёт первый кадр — без него роутер уберёт оболочку', () => {
    const screens = appRoutes()[0]?.children?.[0]?.children ?? []
    const loaded = screens.filter((r) => r.loader)
    expect(loaded.length).toBeGreaterThan(0)
    for (const r of loaded) expect(r.hydrateFallbackElement, r.path).toBeTruthy()
  })

  it('адреса, которого нет у сервера, у роутера тоже нет', () => {
    expect(winner('/dashboard')).toBe('*')
    expect(winner('/admin/pacienti')).toBe('*')
  })
})

describe('App', () => {
  it('известный экран монтируется по адресу', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    open('/admin/settings/clinic', node('settings_clinic'))
    expect(screen.getByLabelText('Nume')).toBeTruthy()
  })

  it('экран на загрузчике: пока ответа нет, оболочка на месте, а экран в ожидании', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    open('/admin/settings', node('settings_hub', {}, SHELL))
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Setări')
    expect(document.querySelector('section.dp-react-root')?.getAttribute('aria-busy')).toBe('true')
    expect(get).toHaveBeenCalledWith('/settings/hub', expect.anything())
  })

  it('визит: номер — из пути appt_id, back — из АДРЕСА, а не из узла (aid, back)', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    open('/admin/visit/42?back=%2Fadmin%2Fall', node('visit', { aid: '999', back: '/admin/week' }))
    expect(get).toHaveBeenCalledWith('/visits/42?back=%2Fadmin%2Fall', expect.anything())
  })

  it('адрес, которого роутер не знает: экран называется по имени, выход — перезагрузка', () => {
    open('/admin/fisa', node('fisa'))
    expect(screen.getByRole('alert').textContent).toContain('«fisa»')
    /* старой страницы нет с 13.10 — ссылки «varianta clasică» тоже */
    expect(screen.getByRole('button', { name: 'Reîncarcă' })).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('роутер и сервер разошлись: чужой экран НЕ рисуется, расхождение слышно', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    open('/admin/week', node('stats'))
    expect(screen.getByRole('alert').textContent).toContain('«stats»')
    /* ⚠️ Загрузчик маршрута отработает и тут — роутер спрашивает данные до
       того, как экран решит, что рисовать. Доказательство — отсутствие
       разметки ЧУЖОГО экрана, а не отсутствие запроса. */
    expect(document.querySelector('.week')).toBeNull()
    expect(err.mock.calls.flat().join(' ')).toContain('schedule_week')
  })

  it('упавший экран оставляет оболочку на месте и ведёт на старую страницу', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    open('/admin/settings/faq', node('settings_faq', {}, SHELL))
    expect(screen.getByRole('alert').textContent).toContain('nu a putut fi afișat')
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Setări')
    expect(screen.getByTitle('Setări')).toBeTruthy()
  })

  it('B3: маршрут под правом без права — экран не монтируется, оболочка на месте', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'forbidden', code: 'no_access', text: 'Nu' }, 'f'))
    open('/admin/stats', node('stats', {}, SHELL))
    await waitFor(() => expect(leave).toHaveBeenCalledWith('/admin?msg=no_access'))
    await waitFor(() => expect(document.querySelector('.dp-react-root')).toBeNull())
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Setări')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

/* Модель оболочки ДРУГОГО адреса: другой активный пункт и подпись. */
const SHELL_MED: ShellModel = {
  ...SHELL,
  nav: {
    ...SHELL.nav,
    active: 'med',
    items: [...SHELL.nav.items, { key: 'med', href: '/admin/medici', icon: 'med', label: 'Medici' }],
  },
  frame: { ...SHELL.frame, title: 'Medici', sub: 'medicii clinicii' },
}

const OFFLINE = new ApiError({ kind: 'network', detail: 'x' }, 'x')

/* Хаб настроек ждёт вечно (кадр прежнего адреса), список врачей отвечает
   отказом сети: экран с плашкой — законный конец перехода, и данные нужного
   вида для него не нужны. */
const hubWaitsDoctorsFail = (path: string) =>
  path === '/settings/hub' ? new Promise(() => {}) : Promise.reject(OFFLINE)

describe('B4: переход без перезагрузки', () => {
  it('первый кадр за документом не ходит: узел приехал инлайном', () => {
    get.mockReturnValue(new Promise(() => {}))
    open('/admin/settings', node('settings_hub', {}, SHELL))
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Setări')
    expect(fetchDoc).not.toHaveBeenCalled()
  })

  it('другой путь: оболочка та же (узлы не пересозданы), модель — из документа нового адреса', async () => {
    get.mockImplementation(hubWaitsDoctorsFail)
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('doctors_list', {}, SHELL_MED) })
    const { router } = open('/admin/settings', node('settings_hub', {}, SHELL))
    const aside = document.querySelector('aside.side')
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(document.querySelector('.sub')?.textContent).toContain('setări')

    await act(() => router.navigate('/admin/medici'))

    expect(fetchDoc).toHaveBeenCalledWith(expect.stringContaining('/admin/medici'), expect.any(AbortSignal))
    expect(document.querySelector('.sub')?.textContent).toContain('medicii clinicii')
    expect(document.querySelector('aside nav a.on')?.getAttribute('title')).toBe('Medici')
    /* ⭐ Те же узлы, а не пересозданные: сайдбар и шапка не исчезали ни на кадр. */
    expect(document.querySelector('aside.side')).toBe(aside)
    expect(screen.getByRole('heading', { level: 1 })).toBe(h1)
    expect(leave).not.toHaveBeenCalled()
  })

  it('тот же путь, другой query — тот же документ: запроса за ним нет', async () => {
    const wk = (path: string) => Promise.resolve({
      data: { monday: '', sunday: '', prev: '', next: '', span: path, total: 0, days: [], day: '' },
      code: '', text: '', tone: 'ok',
    })
    get.mockImplementation(wk)
    const { router } = open('/admin/week?date=2026-09-21', node('schedule_week', {}, SHELL))
    await screen.findByText(/2026-09-21/)
    await act(() => router.navigate('/admin/week?date=2026-09-28', { replace: true }))
    expect(await screen.findByText(/2026-09-28/)).toBeTruthy()
    expect(fetchDoc).not.toHaveBeenCalled()
  })

  it('перечитывается при смене пути и плашки ?msg=, но не query того же пути', () => {
    const at = (a: string, b: string) =>
      docChanged({ currentUrl: new URL(a, 'http://x'), nextUrl: new URL(b, 'http://x') } as Parameters<typeof docChanged>[0])
    expect(at('/admin/week', '/admin')).toBe(true)
    expect(at('/admin/week?date=2026-09-21', '/admin/week?date=2026-09-28')).toBe(false)
    expect(at('/admin?msg=no_access', '/admin?date=2026-09-25')).toBe(true)
    expect(at('/admin/search?q=a', '/admin/search?q=ab')).toBe(false)
  })

  it('заказ перечитать (смена человека) действует и на том же адресе, и не снимается самим правилом', () => {
    const at = (a: string, b: string) =>
      docChanged({ currentUrl: new URL(a, 'http://x'), nextUrl: new URL(b, 'http://x') } as Parameters<typeof docChanged>[0])
    expect(at('/admin?date=2026-09-25', '/admin')).toBe(false)
    orderDoc()
    expect(at('/admin?date=2026-09-25', '/admin')).toBe(true)
    /* роутер вправе спросить правило дважды за переход — заказ снимает загрузчик */
    expect(at('/admin?date=2026-09-25', '/admin')).toBe(true)
  })

  it('документ велит уйти — уходим документом, а в окне прежний кадр до конца', async () => {
    get.mockReturnValue(new Promise(() => {}))
    fetchDoc.mockResolvedValue({ kind: 'leave', url: '/admin/login?next=%2Fadmin%2Fmedici' })
    const { router } = open('/admin/settings', node('settings_hub', {}, SHELL))
    act(() => { void router.navigate('/admin/medici') })
    await waitFor(() => expect(leave).toHaveBeenCalledWith('/admin/login?next=%2Fadmin%2Fmedici'))
    expect(router.state.location.pathname).toBe('/admin/settings')
    expect(document.querySelector('.sub')?.textContent).toContain('setări')
  })

  it('голова нового адреса ложится в окно вместе с его кадром', async () => {
    get.mockImplementation(hubWaitsDoctorsFail)
    const head = { title: 'Clinica Nouă — registru', style: 'calm', card: 'time', themeColor: '#123456',
      themeCss: ':root{}' }
    fetchDoc.mockResolvedValue({ kind: 'page', node: { ...node('doctors_list', {}, SHELL_MED), head } })
    const { router } = open('/admin/settings', node('settings_hub', {}, SHELL))
    expect(document.title).not.toBe(head.title)
    await act(() => router.navigate('/admin/medici'))
    expect(document.title).toBe(head.title)
    expect(document.documentElement.dataset.style).toBe('calm')
    expect(document.documentElement.dataset.card).toBe('time')
  })
})

describe('B4.2: оболочка — сайдбар, крошки, шапка, поиск', () => {
  const SHELL_FULL: ShellModel = {
    ...SHELL,
    nav: {
      ...SHELL.nav,
      items: [
        { key: 'dash', href: '/admin', icon: 'home', label: 'Panoul principal' },
        { key: 'med', href: '/admin/medici', icon: 'med', label: 'Medici' },
        { key: 'set', href: '/admin/settings', icon: 'set', label: 'Setări' },
      ],
      sync: [
        { key: 'tg', href: '/admin/settings/telegram', icon: 'bot', label: 'Telegram Bot', dot: 'off' },
        { key: 'qr', href: '/admin/qr-print', icon: 'qr', label: 'QR pacienți' },
      ],
    },
    frame: {
      ...SHELL.frame,
      crumbs: [
        { key: 'set', href: '/admin/settings', icon: 'chev-l', label: 'Setări' },
        { key: 'home', href: '/admin', icon: 'home', label: 'Panou' },
      ],
      update: "<a href='/admin/settings/system'>versiune nouă 9.9.10</a>",
      msg: "<div class='banner ok'>Salvat. <a href='/admin/export.xlsx'>Excel</a></div>",
    },
  }
  const CLINIC_URL = '/admin/settings/clinic'

  function openClinic() {
    get.mockImplementation(hubWaitsDoctorsFail)
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('doctors_list', {}, SHELL_MED) })
    return open(CLINIC_URL, node('settings_clinic', {}, SHELL_FULL))
  }

  /** Переход состоялся роутером: адрес сменился, документ нового адреса запрошен, окно не уходило. */
  async function expectTransition(router: ReturnType<typeof open>['router'], where: string) {
    await waitFor(() => expect(router.state.location.pathname + router.state.location.search).toBe(where))
    expect(fetchDoc).toHaveBeenCalledWith(expect.stringContaining(where), expect.any(AbortSignal))
    expect(leave).not.toHaveBeenCalled()
  }

  it('пункт сайдбара — переход без перезагрузки, активный пункт — из документа нового адреса', async () => {
    const { router } = openClinic()
    let native = true
    await act(async () => { native = nativeClick(screen.getByTitle('Medici')) })
    expect(native).toBe(false)
    await expectTransition(router, '/admin/medici')
    expect(document.querySelector('aside nav a.on')?.getAttribute('title')).toBe('Medici')
  })

  it('12.10: «Restrânge meniul» — узкий сайдбар тем же классом, что у одонтограммы; выбор помнит компьютер', async () => {
    localStorage.removeItem('dp_side')
    openClinic()
    const aside = document.querySelector('aside.side') as HTMLElement
    const btn = screen.getByRole('button', { name: 'Restrânge meniul' })
    expect(aside.className).toBe('side')
    expect(btn.getAttribute('aria-pressed')).toBe('false')
    await act(async () => { fireEvent.click(btn) })
    expect(aside.className).toBe('side side-rail')
    expect(localStorage.getItem('dp_side')).toBe('rail')
    expect(screen.getByRole('button', { name: 'Extinde meniul' }).getAttribute('aria-pressed')).toBe('true')
    /* перезапуск окна: первый же кадр — узкий (выбор читается в первом рендере) */
    cleanup()
    openClinic()
    expect((document.querySelector('aside.side') as HTMLElement).className).toBe('side side-rail')
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Extinde meniul' })) })
    expect((document.querySelector('aside.side') as HTMLElement).className).toBe('side')
    expect(localStorage.getItem('dp_side')).toBeNull()
  })

  it('12.10: на экране, где узость задал сервер (одонтограмма, `rail`), кнопки нет', () => {
    localStorage.removeItem('dp_side')
    get.mockImplementation(hubWaitsDoctorsFail)
    open(CLINIC_URL, node('settings_clinic', {}, { ...SHELL_FULL, frame: { ...SHELL_FULL.frame, rail: true } }))
    expect((document.querySelector('aside.side') as HTMLElement).className).toBe('side side-rail')
    expect(screen.queryByRole('button', { name: 'Restrânge meniul' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Extinde meniul' })).toBeNull()
  })

  it('пункт «Sincronizări» на страницу, которой нет у роутера, — обычная ссылка', async () => {
    const { router } = openClinic()
    let native = false
    await act(async () => { native = nativeClick(screen.getByTitle('Telegram Bot')) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe(CLINIC_URL)
    expect(fetchDoc).not.toHaveBeenCalled()
  })

  it('крошка раздела — переход без перезагрузки', async () => {
    const { router } = openClinic()
    await act(async () => { nativeClick(screen.getByText('Panou')) })
    await expectTransition(router, '/admin')
  })

  it('«+ Programare nouă» — переход, якорь формы остаётся в адресе', async () => {
    const { router } = openClinic()
    await act(async () => { nativeClick(screen.getByText('Programare nouă')) })
    await expectTransition(router, '/admin/all?date=2026-09-24')
    expect(router.state.location.hash).toBe('#addform')
  })

  it('поиск из шапки: Enter в поле ведёт на экран поиска с ?q=, без перезагрузки', async () => {
    const { router } = openClinic()
    const q = document.getElementById('topq') as HTMLInputElement
    fireEvent.change(q, { target: { value: 'Ion Popescu' } })
    await act(async () => { fireEvent.submit(q.closest('form') as HTMLFormElement) })
    await expectTransition(router, '/admin/search?q=Ion+Popescu')
  })

  it('ссылка в серверной прозе (строка обновления) — переход; выгрузка в плашке — документ', async () => {
    const { router } = openClinic()
    /* Сначала плашка: после перехода оболочка уже от другого документа, и
       плашки ответа в ней нет. */
    let native = false
    await act(async () => { native = nativeClick(screen.getByText('Excel')) })
    expect(native).toBe(true)
    expect(fetchDoc).not.toHaveBeenCalled()
    native = true
    await act(async () => { native = nativeClick(screen.getByText('versiune nouă 9.9.10')) })
    expect(native).toBe(false)
    await expectTransition(router, '/admin/settings/system')
  })

  it('выход без PIN-файла (облако, демо) — не экран: обычная ссылка на сервер', async () => {
    get.mockReturnValue(new Promise(() => {}))
    const { router } = open(CLINIC_URL, node('settings_clinic', {}, {
      ...SHELL_FULL,
      identity: { name: 'Ana', role: 'director', role_label: 'Director', initials: 'A',
        can: { money: true, settings: true, doctors: true } },
    }))
    const out = screen.getByTitle('Ieșire din cont')
    expect(out.tagName).toBe('A')
    expect(out.getAttribute('href')).toBe('/admin/logout')
    let native = false
    await act(async () => { native = nativeClick(out) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe(CLINIC_URL)
    expect(post).not.toHaveBeenCalled()
  })

  it('подвал меню (08.10, был уголок 06.10): знак со словом — сайт в СИСТЕМНОМ браузере, почта — письмом; подписи у имени клиники нет', async () => {
    get.mockReturnValue(new Promise(() => {}))
    const { router } = open(CLINIC_URL, node('settings_clinic', {}, SHELL_FULL))
    expect(document.querySelector('.brandcorner')).toBeNull()
    const site = document.querySelector('aside .sfoot a.bc-site') as HTMLAnchorElement
    expect(site.getAttribute('href')).toBe('https://dentpilot.md')
    /* ⛔ Без target=_blank окно программы само ушло бы на сайт — кнопки
       «назад» там нет, вернуться можно лишь перезапуском. */
    expect(site.getAttribute('target')).toBe('_blank')
    expect(site.querySelector('svg.bcmark')).toBeTruthy()
    expect(site.textContent).toBe('DentPilot')
    let native = false
    await act(async () => { native = nativeClick(site) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe(CLINIC_URL)
    const mail = screen.getByText('x@y.md').closest('a') as HTMLAnchorElement
    expect(mail.getAttribute('href')).toBe('mailto:x@y.md')
    expect(document.querySelector('aside .brand b')?.textContent).toBe('Clinica Test')
    expect(document.querySelector('aside .brand small')).toBeNull()
  })

  it('быстрый поиск (Ctrl+K) открывает фишу переходом роутера', async () => {
    /* Список — ответ поиска; фиша отвечает отказом сети: экран с плашкой —
       законный конец перехода (загрузчик, который ждёт вечно, перехода бы не
       завершил). */
    get.mockImplementation((path: string) => path.startsWith('/patients?')
      ? Promise.resolve({ data: { rows: [{ id: 33, name: 'Ion Popescu', initials: 'IP', phone: '', doctor: '' }] },
                         code: '', text: '', tone: 'ok' })
      : Promise.reject(OFFLINE))
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('patient_card', {}, SHELL_MED) })
    const { router } = open(CLINIC_URL, node('settings_clinic', {}, SHELL_FULL))
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const field = await screen.findByLabelText('Nume sau telefon…')
    fireEvent.change(field, { target: { value: 'Ion' } })
    await screen.findByText('Ion Popescu')
    await act(async () => { fireEvent.keyDown(field, { key: 'Enter' }) })
    await expectTransition(router, '/admin/patient/33')
  })

  /* ⭐ С 06.10 неделя — раздел «Programări», и день из её шапки — день
     журнала (`/admin/all`), а не панель. */
  it('B4.3: ссылка ВНУТРИ экрана (колонка недели → день журнала) — переход роутером', async () => {
    const wk = { monday: '2026-09-21', sunday: '2026-09-27', prev: '2026-09-14', next: '2026-09-28',
      span: '21.09 – 27.09.2026', total: 0, day: '2026-09-21',
      days: [{ date: '2026-09-23', label: 'Mi', dm: '23.09', count: 0, today: false, items: [] }] }
    get.mockImplementation((path: string) => path.startsWith('/schedule/week')
      ? Promise.resolve({ data: wk, code: '', text: '', tone: 'ok' })
      : Promise.reject(OFFLINE))
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('schedule_all', {}, SHELL_MED) })
    const { router } = open('/admin/week', node('schedule_week', {}, SHELL_FULL))
    const col = await screen.findByText('Mi 23.09')
    let native = true
    await act(async () => { native = nativeClick(col) })
    expect(native).toBe(false)
    await expectTransition(router, '/admin/all?date=2026-09-23')
  })
})

describe('B4.4: смена человека без перезагрузки', () => {
  const ION: ShellModel['identity'] = { name: 'Ion Director', role: 'director', role_label: 'Director',
    initials: 'ID', can: { money: true, settings: true, doctors: true } }
  const ANA: ShellModel['identity'] = { name: 'Ana Recepție', role: 'receptie', role_label: 'Recepție',
    initials: 'AR', can: { money: false, settings: false, doctors: true } }
  /* клиника с PIN-файлом: дверь — замок на месте */
  const PIN_SHELL: ShellModel = {
    ...SHELL, identity: ION,
    clinic: { ...SHELL.clinic, logo: '/admin/clinic-logo' },
    entry: { pin: true, pin_max: 8, backdrop: '<div class="dp-bg" data-x="фон"></div>' },
  }
  /* документ панели, каким его отдаст сервер уже Ане: другое имя, меню по её правам */
  const DASH_ANA: ShellModel = {
    ...PIN_SHELL, identity: ANA,
    nav: { ...SHELL.nav, active: 'dash', items: [{ key: 'dash', href: '/admin', icon: 'home', label: 'Panoul principal' }] },
    frame: { ...SHELL.frame, title: 'Panoul principal', sub: '' },
  }
  const OK = { data: null, code: '', text: '', tone: 'ok' as const }
  const CLINIC_URL = '/admin/settings/clinic'

  function openAsIon(url = CLINIC_URL, screenName = 'settings_clinic') {
    get.mockReturnValue(new Promise(() => {}))
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('schedule_dash', {}, DASH_ANA) })
    return open(url, node(screenName, {}, PIN_SHELL))
  }

  async function leaveClick() {
    const out = screen.getByTitle('Ieșire din cont')
    expect(out.tagName).toBe('BUTTON')
    await act(async () => { fireEvent.click(out) })
  }

  async function enterPin(pin: string) {
    fireEvent.change(await screen.findByLabelText('PIN'), { target: { value: pin } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Intră' })) })
  }

  it('«Ieșire din cont» — запрос, не документ: кука снята сервером, вместо журнала экран PIN', async () => {
    post.mockResolvedValue(OK)
    openAsIon()
    expect(screen.getByLabelText('Nume')).toBeTruthy()
    await leaveClick()
    expect(post).toHaveBeenCalledWith('/auth/logout')
    /* ⭐ Прошлого человека в окне нет: ни оболочки, ни экрана — только карточка PIN */
    expect(await screen.findByLabelText('PIN')).toBeTruthy()
    expect(document.querySelector('aside.side')).toBeNull()
    expect(screen.queryByLabelText('Nume')).toBeNull()
    expect(screen.queryByText('Ion Director')).toBeNull()
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Clinica Test')
    expect((document.querySelector('.dp-lock-card img.clogo') as HTMLImageElement).getAttribute('src')).toBe('/admin/clinic-logo')
    expect(document.querySelector('.dp-lock [data-x="фон"]')).toBeTruthy()
    expect(screen.getByText('DentPilot v9.9.9')).toBeTruthy()
    expect(leave).not.toHaveBeenCalled()
  })

  it('верный PIN: документ панели перечитан, журнал нового человека — переходом, одним деревом', async () => {
    post.mockImplementation((path: string) => Promise.resolve(path === '/auth/login'
      ? { ...OK, data: { uid: 'ana', name: 'Ana Recepție' } } : OK))
    const { router } = openAsIon()
    await leaveClick()
    await enterPin('3333')
    expect(post).toHaveBeenCalledWith('/auth/login', { pin: '3333', uid: '' })
    await waitFor(() => expect(screen.getByText('Ana Recepție')).toBeTruthy())
    expect(router.state.location.pathname).toBe('/admin')
    expect(fetchDoc).toHaveBeenCalledWith(expect.stringContaining('/admin'), expect.any(AbortSignal))
    expect(document.querySelector('aside nav a.on')?.getAttribute('title')).toBe('Panoul principal')
    expect(screen.queryByLabelText('PIN')).toBeNull()
    expect(screen.queryByText('Ion Director')).toBeNull()
    expect(leave).not.toHaveBeenCalled()
  })

  it('тот же адрес панели — документ всё равно перечитан (заказ), а следующий переход по дате — нет', async () => {
    post.mockResolvedValue({ ...OK, data: { uid: 'ana', name: 'Ana Recepție' } })
    const { router } = openAsIon('/admin?date=2026-09-25', 'schedule_dash')
    await leaveClick()
    await enterPin('3333')
    await waitFor(() => expect(screen.getByText('Ana Recepție')).toBeTruthy())
    expect(fetchDoc).toHaveBeenCalledTimes(1)
    expect(router.state.location.pathname + router.state.location.search).toBe('/admin')
    /* заказ снят загрузчиком: листание панели — тот же документ, как и было */
    await act(() => router.navigate('/admin?date=2026-09-26', { replace: true }))
    expect(fetchDoc).toHaveBeenCalledTimes(1)
  })

  it('неверный PIN — слово сервера на месте, замок стоит, документ не трогали', async () => {
    post.mockImplementation((path: string) => path === '/auth/login'
      ? Promise.reject(new ApiError({ kind: 'validation', code: 'login_bad', text: 'PIN greșit', field: 'pin' }, 'v'))
      : Promise.resolve(OK))
    openAsIon()
    await leaveClick()
    await enterPin('1111')
    expect((await screen.findByRole('alert')).textContent).toBe('PIN greșit')
    expect((screen.getByLabelText('PIN') as HTMLInputElement).value).toBe('')
    expect(screen.getByRole('button', { name: 'Intră' })).toBeTruthy()
    expect(fetchDoc).not.toHaveBeenCalled()
    expect(leave).not.toHaveBeenCalled()
  })

  it('блокировка подбора — текст сервера и выход для забывшего PIN', async () => {
    post.mockImplementation((path: string) => path === '/auth/login'
      ? Promise.reject(new ApiError({ kind: 'server', status: 423, code: 'lock_pin',
        text: 'Prea multe încercări greșite — așteptați câteva minute' }, 'l'))
      : Promise.resolve(OK))
    openAsIon()
    await leaveClick()
    await enterPin('1111')
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Prea multe încercări')
    expect(alert.textContent).toContain('Ați uitat PIN-ul?')
  })

  it('выход при уже мёртвой куке (401) — замок всё равно ставится: снаружи и так', async () => {
    post.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u'))
    openAsIon()
    await leaveClick()
    expect(await screen.findByLabelText('PIN')).toBeTruthy()
    expect(leave).not.toHaveBeenCalled()
  })

  it('движок на выход не ответил — выход документом, как было, замка нет', async () => {
    post.mockRejectedValue(new ApiError({ kind: 'network', detail: 'x' }, 'n'))
    openAsIon()
    await leaveClick()
    await waitFor(() => expect(leave).toHaveBeenCalledWith('/admin/logout'))
    expect(screen.queryByLabelText('PIN')).toBeNull()
    expect(screen.getByLabelText('Nume')).toBeTruthy()
  })
})
