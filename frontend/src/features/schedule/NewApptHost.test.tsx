import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { App, appHydration, appRoutes, type MountNode } from '../../app/App'
import { installShellBridge, type DpShell } from '../../app/bridge'
import type { MenuItem } from '../../app/commands'
import type { ShellModel } from '../../layouts/shell'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { VisitPage } from '../visits/visits'
import type { DayForm } from './day'

/* «Programare nouă» вне дня журнала (22.10, Олег): окно поверх экрана, где
   стоишь, без перехода; экран под ним не перечитывается и ввод в нём цел;
   после записи — плашка со ссылкой в журнал. Живой App: роутер, оболочка,
   мост окна Tauri. Окно дня журнала (`#addform`) — DayScreen.test. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})
const { fetchDoc } = vi.hoisted(() => ({ fetchDoc: vi.fn() }))
vi.mock('../../services/doc', () => ({ fetchDoc }))
const { leave } = vi.hoisted(() => ({ leave: vi.fn() }))
vi.mock('../../hooks/useLoad', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../hooks/useLoad')>(),
  defaultNavigate: leave,
}))

/* Фиша — заглушкой с полем ввода: проверяется ОБОЛОЧКА (перешли ли, перезапущен
   ли загрузчик маршрута, пересоздан ли экран), а не фиша, и её модель в сотню
   строк здесь ничего не добавила бы. Настоящий экран с полем — дневник визита
   ниже. ⚠️ `createElement`, не JSX: фабрика подмены исполняется раньше
   импортов файла. */
const { fisaLoad, mounts } = vi.hoisted(() => ({ fisaLoad: vi.fn(), mounts: { n: 0 } }))
vi.mock('../patients/card/PatientCardScreen', async () => {
  const { createElement, useEffect, useState } = await import('react')
  function PatientCardScreen() {
    const [text, setText] = useState('')
    useEffect(() => { mounts.n += 1 }, [])
    return createElement('section', { className: 'dp-react-root' },
      createElement('textarea', { 'aria-label': 'Notă fișă', value: text,
        onChange: (e: { target: { value: string } }) => setText(e.target.value) }))
  }
  return { PatientCardScreen, loadPatientCard: { load: fisaLoad } }
})

const ok = <T,>(data: T, code = '', text = '', tone: 'ok' | 'warn' = 'ok'): ApiResult<T> =>
  ({ data, code, text, tone })

const TODAY = '2026-10-22'
const FORM: DayForm = {
  doctors: [{ id: 'd2', name: 'Dr. Activ Doi', spec: '' }, { id: 'd3', name: 'Dr. Activ Trei', spec: '' }],
  times: { d2: ['09:00', '09:30', '10:00'], d3: ['10:00', '10:30'] },
  hours: ['09:00', '09:30', '10:00', '10:30'],
  services: [{ id: 'consult', label: 'Consultație' }],
  doctor: 'd2', time: '09:30', birth_max: TODAY,
}

const VPAGE: VisitPage = {
  appt: { id: 3, when: '22.10.2026 09:30', patient_id: 5, patient: 'Pin Test', service: 'Consultație',
    doctor: 'Dr. Activ Doi', status: 'confirmed', status_label: 'confirmată', comment: '' },
  record: null, editable: true, note: '',
  fields: [{ id: 'acuze', label: 'Acuze / motivul prezentării', rows: 2, placeholder: '' }],
  templates: [], plan: { linked: [], open: [] },
  back: '/admin/patient/5',
}

const SHELL: ShellModel = {
  identity: { name: 'Ana Recepție', role: 'receptie', role_label: 'Recepție', initials: 'AR',
    can: { money: false, settings: false, doctors: true, schedule_all: true }, doctor: '' },
  clinic: { name: 'Clinica Test', mark: '', logo_topbar: '', logo: '' },
  runtime: { version: '9.9.9', tz: 'Europe/Chisinau' },
  about: { data: '', license_until: '' },
  entry: { pin: true, pin_max: 8, backdrop: '' },
  nav: { active: 'pat', items: [
    { key: 'dash', href: '/admin', icon: 'home', label: 'Panoul principal' },
    { key: 'prog', href: '/admin/all', icon: 'cal', label: 'Programări' },
    { key: 'pat', href: '/admin/search', icon: 'pat', label: 'Pacienți' },
  ], sync: [], foot_title: '' },
  signals: {
    license: { shown: false, html: '' }, tamper: { shown: false, html: '' },
    split: { shown: false, html: '' }, slot: { shown: false, html: '' },
    setup: { shown: false, html: '' }, demo: { shown: false, html: '' },
    backup: { shown: false, html: '' },
  },
  frame: {
    title: 'Pacienți', sub: '', crumbs: [], rail: false, update: '', msg: '',
    site: { href: 'https://dentpilot.md', mark: '' },
    feedback: { email: 'x@y.md', href: 'mailto:x@y.md' }, today: '2026-10-21',
  },
}

const OFFLINE = new ApiError({ kind: 'network', detail: 'test' }, 'offline')

/** Сервер: форма окна — день БЕЗ даты («сегодня» сервера), дневник визита;
 *  остальное — отказ сети (экран с плашкой — законный конец перехода). */
function serve() {
  fisaLoad.mockResolvedValue(ok({}))
  get.mockImplementation((path: string) => {
    if (path === '/schedule/day') return Promise.resolve(ok({ date: TODAY, form: FORM }))
    if (path.startsWith('/visits/3')) return Promise.resolve(ok(VPAGE))
    return Promise.reject(OFFLINE)
  })
}

const node = (name: string): MountNode => ({ screen: name, params: {}, shell: SHELL })

let dispose: () => void = () => {}

function open(url: string, name: string, { shell = false } = {}) {
  const router = createMemoryRouter(appRoutes(), { initialEntries: [url], hydrationData: appHydration(node(name)) })
  if (shell) window.dpShell = { v: 1, version: '0.1.0', send: vi.fn() } satisfies DpShell
  dispose = installShellBridge(router, SHELL)
  return { router, ...render(<App router={router} />) }
}

const here = (r: ReturnType<typeof open>['router']) =>
  r.state.location.pathname + r.state.location.search + r.state.location.hash
const addDialog = () => document.querySelector('dialog.dp-adddlg') as HTMLDialogElement | null
const newBtn = () => screen.getByText('Programare nouă', { selector: '.nb-t' }).closest('a') as HTMLAnchorElement
const fisaNote = () => screen.getByLabelText('Notă fișă') as HTMLTextAreaElement

/** Фиша открыта, заметка в поле набрана. */
async function onFisa(opts: { shell?: boolean } = {}) {
  serve()
  const r = open('/admin/patient/5?tab=date', 'patient_card', opts)
  fireEvent.change(await screen.findByLabelText('Notă fișă'), { target: { value: 'Dr. Doi: carie 26, revine joi' } })
  return r
}

async function fillAndSend() {
  const d = addDialog() as HTMLDialogElement
  fireEvent.change(d.querySelector('input[placeholder="Nume pacient"]') as HTMLInputElement,
    { target: { value: 'Maria Al Doilea' } })
  fireEvent.change(d.querySelector('input[placeholder="Telefon"]') as HTMLInputElement,
    { target: { value: '069111222' } })
  await act(async () => { fireEvent.submit(d.querySelector('form') as HTMLFormElement) })
}

beforeAll(() => { window.scrollTo = vi.fn() as unknown as typeof window.scrollTo })

afterEach(() => {
  cleanup()
  dispose()
  delete window.dpShell
  get.mockReset()
  post.mockReset()
  fetchDoc.mockReset()
  fisaLoad.mockReset()
  leave.mockReset()
  mounts.n = 0
  vi.restoreAllMocks()
})

describe('«Programare nouă» с фиши — окно на месте', () => {
  it('окно открывается без перехода: адрес, документ и фиша те же, ввод цел, пациента в окне нет', async () => {
    const { router } = await onFisa()
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    expect(here(router)).toBe('/admin/patient/5?tab=date')
    expect(fetchDoc).not.toHaveBeenCalled()
    expect(fisaLoad).toHaveBeenCalledTimes(1)
    expect(mounts.n).toBe(1)
    expect(fisaNote().value).toBe('Dr. Doi: carie 26, revine joi')
    /* форма — день БЕЗ даты: «сегодня» говорит сервер, не модель шапки (21.10) */
    expect(get).toHaveBeenCalledWith('/schedule/day', expect.anything())
    const d = addDialog() as HTMLDialogElement
    expect((d.querySelector('input[type=date]') as HTMLInputElement).value).toBe(TODAY)
    expect((d.querySelector('input[placeholder="Nume pacient"]') as HTMLInputElement).value).toBe('')
    expect((d.querySelector('input[placeholder="Telefon"]') as HTMLInputElement).value).toBe('')
  })

  it('запись: без состояния (`screen=new_appt`), окно закрыто, плашка со ссылкой в журнал; фиша не тронута', async () => {
    const { router } = await onFisa()
    post.mockResolvedValue(ok(undefined, 'ok', 'Programare adăugată'))
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    await fillAndSend()
    expect(post).toHaveBeenCalledWith('/schedule/appointments?screen=new_appt', {
      date: TODAY, time: '09:30', doctor: 'd2', service: 'consult', name: 'Maria Al Doilea',
      phone: '069111222', nophone: false, birth: '',
    })
    await waitFor(() => expect(addDialog()).toBeNull())
    const toast = document.querySelector('.toastbox') as HTMLElement
    expect(toast.textContent).toContain('Programare adăugată')
    const link = screen.getByRole('link', { name: 'Vezi în jurnal ›' })
    expect(link.getAttribute('href')).toBe(`/admin/all?date=${TODAY}`)
    expect(here(router)).toBe('/admin/patient/5?tab=date')
    expect(fisaLoad).toHaveBeenCalledTimes(1)
    expect(mounts.n).toBe(1)
    expect(fisaNote().value).toBe('Dr. Doi: carie 26, revine joi')
    /* ссылка — переход роутером, плашка уходит вместе с ним */
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('schedule_all') })
    await act(async () => { fireEvent.click(link) })
    await waitFor(() => expect(here(router)).toBe(`/admin/all?date=${TODAY}`))
    expect(document.querySelector('.toastbox')).toBeNull()
    expect(leave).not.toHaveBeenCalled()
  })

  it('предупреждение сервера (`ok_other`) — его словом и тоном: висит, пока не закроют', async () => {
    await onFisa()
    post.mockResolvedValue(ok(undefined, 'ok_other', 'Programare adăugată — dar la fișa unui pacient', 'warn'))
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    await fillAndSend()
    const toast = await waitFor(() => document.querySelector('.toastbox[data-kind=warn]') as HTMLElement)
    expect(toast.textContent).toContain('la fișa unui pacient')
    expect(screen.getByRole('link', { name: 'Vezi în jurnal ›' })).toBeTruthy()
  })

  it('отказ — словом сервера В ОКНЕ: окно открыто, набранное цело, плашки нет', async () => {
    await onFisa()
    post.mockRejectedValue(new ApiError(
      { kind: 'conflict', code: 'conflict', text: 'Intervalul este deja ocupat la acest medic' }, 'c'))
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    await fillAndSend()
    const d = addDialog() as HTMLDialogElement
    expect(d.open).toBe(true)
    expect(d.querySelector('[role=alert]')?.textContent).toBe('Intervalul este deja ocupat la acest medic')
    expect((d.querySelector('input[placeholder="Nume pacient"]') as HTMLInputElement).value).toBe('Maria Al Doilea')
    expect(document.querySelector('.toastbox')).toBeNull()
  })

  it('«Închide» закрывает окно; следующее открытие — с чистого листа', async () => {
    await onFisa()
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    fireEvent.change((addDialog() as HTMLDialogElement).querySelector('input[placeholder="Nume pacient"]') as HTMLInputElement,
      { target: { value: 'Ciornă' } })
    fireEvent.click(screen.getByRole('button', { name: 'Închide' }))
    await waitFor(() => expect(addDialog()).toBeNull())
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    expect(((addDialog() as HTMLDialogElement).querySelector('input[placeholder="Nume pacient"]') as HTMLInputElement).value).toBe('')
    expect(fisaNote().value).toBe('Dr. Doi: carie 26, revine joi')
  })

  it('форма не пришла — плашка отказа, окна нет; 401 — на вход', async () => {
    serve()
    get.mockImplementation(() => Promise.reject(OFFLINE))
    fisaLoad.mockResolvedValue(ok({}))
    open('/admin/patient/5', 'patient_card')
    await screen.findByLabelText('Notă fișă')
    fireEvent.click(newBtn())
    await waitFor(() => expect(document.querySelector('.toastbox[data-kind=err]')).not.toBeNull())
    expect(addDialog()).toBeNull()
    get.mockImplementation(() => Promise.reject(new ApiError({ kind: 'unauthenticated' }, '')))
    fireEvent.click(newBtn())
    await waitFor(() => expect(leave).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})

describe('настоящий экран под окном — дневник визита', () => {
  it('записи врача в поле целы, дневник не перечитан', async () => {
    serve()
    const { router } = open('/admin/visit/3?back=%2Fadmin%2Fpatient%2F5', 'visit')
    const acuze = await screen.findByLabelText('Acuze / motivul prezentării') as HTMLTextAreaElement
    fireEvent.change(acuze, { target: { value: 'Durere la rece, 26' } })
    const visitGets = () => get.mock.calls.filter(([p]) => String(p).startsWith('/visits/3')).length
    expect(visitGets()).toBe(1)
    post.mockResolvedValue(ok(undefined, 'ok', 'Programare adăugată'))
    fireEvent.click(newBtn())
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    await fillAndSend()
    await screen.findByRole('link', { name: 'Vezi în jurnal ›' })
    expect(here(router)).toBe('/admin/visit/3?back=%2Fadmin%2Fpatient%2F5')
    expect(visitGets()).toBe(1)
    expect((screen.getByLabelText('Acuze / motivul prezentării') as HTMLTextAreaElement).value).toBe('Durere la rece, 26')
  })
})

describe('Ctrl+N и меню окна Tauri — туда же', () => {
  it('Ctrl+N (и при русской раскладке) открывает то же окно без перехода', async () => {
    const { router } = await onFisa({ shell: true })
    let free = true
    await act(async () => { free = fireEvent.keyDown(document.body, { code: 'KeyN', key: 'т', ctrlKey: true }) })
    expect(free).toBe(false)
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    expect(here(router)).toBe('/admin/patient/5?tab=date')
    expect(fetchDoc).not.toHaveBeenCalled()
    expect(fisaNote().value).toBe('Dr. Doi: carie 26, revine joi')
  })

  it('пункт «Programare nouă…» заявлен кнопкой шапки и открывает то же окно', async () => {
    const { router } = await onFisa({ shell: true })
    const item = () => window.dpMenu?.('file').items
      .find((e): e is MenuItem => !('sep' in e) && e.id === 'act:newAppt')
    await waitFor(() => expect(item()?.enabled).toBe(true))
    act(() => { expect(window.dpRun?.('act:newAppt')).toBe(true) })
    await waitFor(() => expect(addDialog()?.open).toBe(true))
    expect(here(router)).toBe('/admin/patient/5?tab=date')
    expect(fisaLoad).toHaveBeenCalledTimes(1)
  })
})

describe('на дне журнала — как раньше', () => {
  it('кнопка и Ctrl+N ведут на окно ЭТОГО дня (`#addform`), окна оболочки нет', async () => {
    serve()
    fetchDoc.mockResolvedValue({ kind: 'page', node: node('schedule_all') })
    const { router } = open('/admin/all?date=2026-10-23', 'schedule_all', { shell: true })
    expect(newBtn().getAttribute('href')).toBe('/admin/all?date=2026-10-23#addform')
    await act(async () => { fireEvent.click(newBtn()) })
    await waitFor(() => expect(here(router)).toBe('/admin/all?date=2026-10-23#addform'))
    await act(async () => { await router.navigate('/admin/all?date=2026-10-23', { replace: true }) })
    await act(async () => { fireEvent.keyDown(document.body, { code: 'KeyN', key: 'n', ctrlKey: true }) })
    await waitFor(() => expect(here(router)).toBe('/admin/all?date=2026-10-23#addform'))
    /* форму дня берёт экран дня своим запросом; окно оболочки не спрашивало */
    expect(get).not.toHaveBeenCalledWith('/schedule/day', expect.anything())
  })
})
