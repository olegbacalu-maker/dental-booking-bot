import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ShellModel } from '../layouts/shell'
import { ApiError } from '../types/api'
import { App, appHydration, appRoutes, type MountNode } from './App'
import { installShellBridge, type DpShell } from './bridge'
import type { MenuEntry, MenuItem } from './commands'

/* Мост к оболочке Tauri (Т7) на живом App: меню строится по модели документа и
   по тому, что заявили смонтированные экраны; клавиши — по тому же списку;
   без `window.dpShell` — ничего. Чистый список — commands.test. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})
const { fetchDoc } = vi.hoisted(() => ({ fetchDoc: vi.fn() }))
vi.mock('../services/doc', () => ({ fetchDoc }))
const { leave } = vi.hoisted(() => ({ leave: vi.fn() }))
vi.mock('../hooks/useLoad', async (importOriginal) => ({
  ...await importOriginal<typeof import('../hooks/useLoad')>(),
  defaultNavigate: leave,
}))
const { reload } = vi.hoisted(() => ({ reload: vi.fn() }))
vi.mock('../hooks/useLive', async (importOriginal) => ({
  ...await importOriginal<typeof import('../hooks/useLive')>(),
  defaultReload: reload,
}))

const ION: ShellModel['identity'] = { name: 'Ion Director', role: 'director', role_label: 'Director',
  initials: 'ID', can: { money: true, settings: true, doctors: true } }
const ANA: ShellModel['identity'] = { name: 'Ana Recepție', role: 'receptie', role_label: 'Recepție',
  initials: 'AR', can: { money: false, settings: false, doctors: true } }

const NAV = [
  { key: 'dash', href: '/admin', icon: 'home', label: 'Panoul principal' },
  { key: 'prog', href: '/admin/all', icon: 'cal', label: 'Programări' },
  { key: 'pat', href: '/admin/search', icon: 'pat', label: 'Pacienți' },
  { key: 'med', href: '/admin/medici', icon: 'med', label: 'Medici' },
  { key: 'stat', href: '/admin/stats', icon: 'stat', label: 'Statistici' },
  { key: 'set', href: '/admin/settings', icon: 'set', label: 'Setări' },
]

const SHELL: ShellModel = {
  identity: ION,
  clinic: { name: 'Clinica Test', mark: '', logo_topbar: '', logo: '' },
  runtime: { version: '9.9.9', tz: 'Europe/Chisinau' },
  about: { data: 'C:\\ProgramData\\DentPilot', license_until: '31.12.2026' },
  entry: { pin: true, pin_max: 8, backdrop: '' },
  nav: { active: 'set', items: NAV, sync: [], foot_title: '' },
  signals: {
    license: { shown: false, html: '' }, tamper: { shown: false, html: '' },
    split: { shown: false, html: '' }, slot: { shown: false, html: '' },
    setup: { shown: false, html: '' }, demo: { shown: false, html: '' },
    backup: { shown: false, html: '' },
  },
  frame: {
    title: 'Setări', sub: '', crumbs: [], rail: false, update: '', msg: '',
    site: { href: 'https://dentpilot.md', mark: '' },
    feedback: { email: 'x@y.md', href: 'mailto:x@y.md' }, today: '2026-10-18',
  },
}

const PATIENTS_SUMMARY = {
  tiles: [{ icon: 'users', tone: 'g', value: '2', foot: '+1', href: '' }],
  doctors: [], channels: [], statuses: [], per: [20], clinic_doctors: ['Dr. Unu'],
}
const PATIENTS_PAGE = { rows: [], total: 0, page: 1, pages: 1, per: 20, sort: 'last', hidden_arh: 0, n_arh: 0 }
const ok = <T,>(data: T) => ({ data, code: '', text: '', tone: 'ok' as const })

const OFFLINE = new ApiError({ kind: 'network', detail: 'test' }, 'offline')

/** Сеть: список пациентов отвечает, остальные экраны — отказом сети: экран с
 *  плашкой — законный конец перехода (как в App.test), и переход не виснет. */
function serve() {
  get.mockImplementation((path: string) => {
    if (path === '/patients/summary') return Promise.resolve(ok(PATIENTS_SUMMARY))
    if (path.startsWith('/patients')) return Promise.resolve(ok(PATIENTS_PAGE))
    return Promise.reject(OFFLINE)
  })
}

const node = (screenName: string, shell: ShellModel = SHELL): MountNode => ({ screen: screenName, params: {}, shell })

const SCREEN_OF: Record<string, string> = {
  '/admin/search': 'patients_search', '/admin/medici': 'doctors_list',
  '/admin/all': 'schedule_all', '/admin/settings': 'settings_hub',
}

/** Документ нового адреса — узел его экрана с моделью `shell`. */
function docs(shell: ShellModel = SHELL) {
  fetchDoc.mockImplementation((url: string) =>
    Promise.resolve({ kind: 'page', node: node(SCREEN_OF[new URL(url).pathname] ?? 'unknown', shell) }))
}

let send = vi.fn()
let dispose: () => void = () => {}

/** Окно, как его открывает main.tsx: роутер, мост (если окно оболочки), App. */
function open(url: string, n: MountNode, { shell = true } = {}) {
  const router = createMemoryRouter(appRoutes(), { initialEntries: [url], hydrationData: appHydration(n) })
  if (shell) {
    send = vi.fn()
    window.dpShell = { v: 1, version: '0.1.0', send } satisfies DpShell
  }
  dispose = installShellBridge(router, n.shell)
  return { router, ...render(<App router={router} />) }
}

const menu = (id: string): MenuEntry[] => window.dpMenu?.(id).items ?? []
const item = (id: string, menuId: string) =>
  menu(menuId).find((e): e is MenuItem => !('sep' in e) && e.id === id)

/** Нажатие в окне; ответ — досталось ли оно браузеру (действие не отменено). */
function press(code: string, init: KeyboardEventInit = {}, target: Element = document.body): boolean {
  return fireEvent.keyDown(target, { code, ...init })
}

beforeAll(() => { window.scrollTo = vi.fn() as unknown as typeof window.scrollTo })

afterEach(() => {
  cleanup()
  dispose()
  delete window.dpShell
  get.mockReset()
  post.mockReset()
  fetchDoc.mockReset()
  leave.mockReset()
  reload.mockReset()
  vi.restoreAllMocks()
})

describe('без окна оболочки — ничего', () => {
  it('браузер второго ПК, телефон: ни функций, ни клавиш, ни «Despre»', () => {
    serve()
    open('/admin/settings', node('settings_hub'), { shell: false })
    expect(window.dpMenu).toBeUndefined()
    expect(window.dpRun).toBeUndefined()
    expect(window.dpCtx).toBeUndefined()
    /* Ctrl+N и F5 остаются браузеру — никто их не отменил */
    expect(press('KeyN', { key: 'n', ctrlKey: true })).toBe(true)
    expect(press('F5', { key: 'F5' })).toBe(true)
    expect(document.querySelector('dialog.dp-about')).toBeNull()
  })

  it('оболочка чужой версии контракта — тоже ничего, и это слышно', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    window.dpShell = { v: 2, version: '9', send: vi.fn() }
    serve()
    open('/admin/settings', node('settings_hub'), { shell: false })
    expect(window.dpMenu).toBeUndefined()
    expect(err.mock.calls.flat().join(' ')).toContain('v2')
  })
})

describe('меню — по модели документа и по экрану', () => {
  it('«Mergi la» — пункты левого меню этого документа; переход — роутером', async () => {
    serve()
    docs()
    const { router } = open('/admin/settings', node('settings_hub'))
    expect(menu('go').slice(0, 2)).toEqual([
      { id: 'go:/admin', label: 'Panoul principal', accel: 'Ctrl+1', enabled: true },
      { id: 'go:/admin/all', label: 'Programări', accel: 'Ctrl+2', enabled: true },
    ])
    await act(async () => { expect(window.dpRun?.('go:/admin/medici')).toBe(true) })
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/medici'))
    expect(leave).not.toHaveBeenCalled()
  })

  it('регистратура: меню по ЕЁ модели — без кассы, копии, справки; Ctrl+5 — не пункт', () => {
    serve()
    const m = { ...SHELL, identity: ANA, nav: { ...SHELL.nav, items: NAV.slice(0, 4) } }
    open('/admin/settings', node('settings_hub', m))
    expect(item('go:/admin/casa', 'file')).toBeUndefined()
    expect(item('act:backupNow', 'file')).toBeUndefined()
    expect(item('go:/admin/settings/faq', 'help')).toBeUndefined()
    expect(press('Digit5', { key: '5', ctrlKey: true })).toBe(true)
  })

  it('экран без печати и выгрузки — пункты серые, Ctrl+P браузеру тоже не достаётся', () => {
    serve()
    open('/admin/settings', node('settings_hub'))
    expect(item('act:print', 'file')?.enabled).toBe(false)
    expect(item('act:export', 'file')?.enabled).toBe(false)
    expect(window.dpRun?.('act:print')).toBe(false)
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    expect(press('KeyP', { key: 'p', ctrlKey: true })).toBe(false)
    expect(print).not.toHaveBeenCalled()
  })

  it('список пациентов заявляет «Exportă»: пункт живой и ведёт на ту же выгрузку, что кнопка', async () => {
    serve()
    open('/admin/search', node('patients_search'))
    /* заявляет, когда список приехал (пока нет данных, кнопка ещё не та) */
    await waitFor(() => expect(item('act:export', 'file')?.enabled).toBe(true))
    const href = screen.getByTitle('Lista filtrată, ca registru Excel').getAttribute('href')
    act(() => { window.dpRun?.('act:export') })
    expect(leave).toHaveBeenCalledWith(href)
  })

  it('чужой адрес в `go:` не открывается', () => {
    serve()
    open('/admin/settings', node('settings_hub'))
    expect(window.dpRun?.('go://evil.md/x')).toBe(false)
    expect(window.dpRun?.('go:javascript:alert(1)')).toBe(false)
    expect(window.dpRun?.('win:quit')).toBe(false)
    expect(leave).not.toHaveBeenCalled()
  })
})

describe('пункт уходит на свой экран и исполняется там', () => {
  it('«Pacient nou…» (Ctrl+Shift+N) с настроек: переход к пациентам — и диалог открыт', async () => {
    serve()
    docs()
    const { router } = open('/admin/settings', node('settings_hub'))
    await act(async () => { expect(press('KeyN', { key: 'N', ctrlKey: true, shiftKey: true })).toBe(false) })
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/search'))
    const dlg = await screen.findByText('Adaugă pacientul')
    expect(dlg.closest('dialog')?.hasAttribute('open')).toBe(true)
  })

  it('уже на экране пациентов — диалог сразу, без перехода', async () => {
    serve()
    const { router } = open('/admin/search', node('patients_search'))
    await waitFor(() => expect(item('act:export', 'file')?.enabled).toBe(true))
    act(() => { window.dpRun?.('act:newPatient') })
    expect(screen.getByText('Adaugă pacientul').closest('dialog')?.hasAttribute('open')).toBe(true)
    expect(router.state.location.pathname).toBe('/admin/search')
    expect(fetchDoc).not.toHaveBeenCalled()
  })

  it('пришли не туда (переход перебили) — заказ снят и позже не срабатывает', async () => {
    serve()
    docs()
    const { router } = open('/admin/settings', node('settings_hub'))
    /* переход к пациентам перебит щелчком по «Medici» */
    act(() => { window.dpRun?.('act:newPatient') })
    await act(() => router.navigate('/admin/medici'))
    expect(router.state.location.pathname).toBe('/admin/medici')
    await act(() => router.navigate('/admin/search'))
    await screen.findByText('Adaugă pacient')
    expect(screen.getByText('Adaugă pacientul').closest('dialog')?.hasAttribute('open')).toBe(false)
  })
})

describe('клавиши окна', () => {
  it('Ctrl+N — окно записи, как кнопка шапки: на месте, без перехода (22.10); при русской раскладке тоже', async () => {
    serve()
    const base = get.getMockImplementation()
    get.mockImplementation((path: string) => (path === '/schedule/day'
      ? Promise.resolve(ok({ date: '2026-10-18', form: {
        doctors: [{ id: 'd2', name: 'Dr. Unu', spec: '' }], times: { d2: ['09:00'] }, hours: ['09:00'],
        services: [{ id: 'consult', label: 'Consultație' }], doctor: 'd2', time: '09:00', birth_max: '2026-10-18' } }))
      : base?.(path)))
    docs()
    const { router } = open('/admin/settings', node('settings_hub'))
    await act(async () => { expect(press('KeyN', { key: 'т', ctrlKey: true })).toBe(false) })
    await waitFor(() => expect(document.querySelector('dialog.dp-adddlg')?.hasAttribute('open')).toBe(true))
    expect(router.state.location.pathname + router.state.location.hash).toBe('/admin/settings')
    expect(fetchDoc).not.toHaveBeenCalled()
    /* ссылка кнопки — прежняя: Ctrl+щелчок по ней ведёт в журнал */
    expect(screen.getByText('Programare nouă', { selector: '.nb-t' }).closest('a')?.getAttribute('href'))
      .toBe('/admin/all?date=2026-10-18#addform')
  })

  it('Ctrl+F — «Căutare rapidă», та же накладка, что Ctrl+K; Ctrl+K жив', () => {
    serve()
    open('/admin/settings', node('settings_hub'))
    expect(press('KeyF', { key: 'f', ctrlKey: true })).toBe(false)
    expect(screen.getByRole('dialog', { name: 'Căutare rapidă' })).toBeTruthy()
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Căutare rapidă' })).toBeNull()
    fireEvent.keyDown(document, { key: 'k', code: 'KeyK', ctrlKey: true })
    expect(screen.getByRole('dialog', { name: 'Căutare rapidă' })).toBeTruthy()
  })

  it('`win:*` — оболочке: F11, масштаб; зажатый Ctrl+= повторяет, зажатый Ctrl+N — нет', () => {
    serve()
    open('/admin/settings', node('settings_hub'))
    expect(press('F11', { key: 'F11' })).toBe(false)
    expect(press('Equal', { key: '+', ctrlKey: true, shiftKey: true })).toBe(false)
    expect(press('Equal', { key: '=', ctrlKey: true, repeat: true })).toBe(false)
    expect(press('Digit0', { key: '0', ctrlKey: true })).toBe(false)
    expect(send.mock.calls.map((c) => c[0])).toEqual(['win/fullscreen', 'win/zoomin', 'win/zoomin', 'win/zoom0'])
    expect(press('KeyN', { key: 'n', ctrlKey: true, repeat: true })).toBe(false)
    expect(fetchDoc).not.toHaveBeenCalled()
  })

  it('F5 — перезагрузка; Alt+← — назад роутером', async () => {
    serve()
    docs()
    const { router } = open('/admin/settings', node('settings_hub'))
    expect(press('F5', { key: 'F5' })).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
    await act(() => router.navigate('/admin/medici'))
    await act(async () => { press('ArrowLeft', { key: 'ArrowLeft', altKey: true }) })
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/settings'))
  })

  it('⛔ Ctrl+Z/C/V/A в поле — родные: страница их не трогает', () => {
    serve()
    open('/admin/settings', node('settings_hub'))
    const input = document.getElementById('topq') as HTMLInputElement
    for (const k of ['Z', 'Y', 'X', 'C', 'V', 'A']) {
      expect(press(`Key${k}`, { key: k.toLowerCase(), ctrlKey: true }, input), k).toBe(true)
    }
    expect(send).not.toHaveBeenCalled()
  })
})

describe('человек, вход, «Despre»', () => {
  it('«Schimbă persoana…» (Ctrl+L) — та же кнопка выхода шапки; оболочке «ctx», меню без вошедшего', async () => {
    serve()
    post.mockResolvedValue({ data: null, code: '', text: '', tone: 'ok' })
    open('/admin/settings', node('settings_hub'))
    expect(window.dpCtx?.()).toEqual({ v: 1, color: '', logged: true, title: '' })
    await act(async () => { expect(press('KeyL', { key: 'l', ctrlKey: true })).toBe(false) })
    expect(post).toHaveBeenCalledWith('/auth/logout')
    expect(await screen.findByLabelText('PIN')).toBeTruthy()
    expect(send).toHaveBeenCalledWith('ctx')
    expect(window.dpCtx?.().logged).toBe(false)
    expect(menu('file').map((e) => ('sep' in e ? '-' : e.id))).toEqual(['win:quit'])
    /* за экраном PIN переходить некуда */
    expect(window.dpRun?.('go:/admin/medici')).toBe(false)
  })

  it('«Despre DentPilot» — факты модели и версия оболочки; есть и за экраном PIN', async () => {
    serve()
    open('/admin/settings', node('settings_hub'))
    expect(item('act:about', 'help')?.enabled).toBe(true)
    act(() => { window.dpRun?.('act:about') })
    const dlg = screen.getByRole('dialog', { name: 'Despre DentPilot' })
    expect(dlg.hasAttribute('open')).toBe(true)
    const facts = [...dlg.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent])
    expect(facts).toEqual([
      ['Versiunea programului', '9.9.9'],
      ['Versiunea ferestrei', '0.1.0'],
      ['Clinica', 'Clinica Test'],
      ['Dosarul cu datele', 'C:\\ProgramData\\DentPilot'],
      ['Licența valabilă până la', '31.12.2026'],
      ['Site', 'dentpilot.md'],
    ])
    expect(dlg.querySelector('a')?.getAttribute('target')).toBe('_blank')
    fireEvent.click(screen.getAllByRole('button', { name: 'Închide' }).at(-1) as HTMLElement)
    expect(dlg.hasAttribute('open')).toBe(false)
  })

  it('пустые факты (облако, исходники) не рисуются', () => {
    serve()
    open('/admin/settings', node('settings_hub', { ...SHELL, about: { data: '', license_until: '' } }))
    act(() => { window.dpRun?.('act:about') })
    const dts = [...document.querySelectorAll('dialog.dp-about dt')].map((d) => d.textContent)
    expect(dts).toEqual(['Versiunea programului', 'Versiunea ferestrei', 'Clinica', 'Site'])
  })

  it('новая модель того же человека — оболочку не дёргаем; другой человек — «ctx»', async () => {
    serve()
    docs()
    const { router } = open('/admin/settings', node('settings_hub'))
    await act(() => router.navigate('/admin/medici'))
    expect(send).not.toHaveBeenCalled()
    docs({ ...SHELL, identity: ANA })
    await act(() => router.navigate('/admin/settings'))
    expect(send).toHaveBeenCalledWith('ctx')
  })
})
