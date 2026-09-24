import { cleanup, render, screen } from '@testing-library/react'
import { createMemoryRouter, matchRoutes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ShellModel } from '../layouts/shell'
import { App, appRoutes, SCREENS, type MountNode } from './App'
import { ROUTES } from './routes'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

/* Экран, который падает при отрисовке: ловушку ошибок иначе не проверить.
   FAQ выбран потому, что больше ни одна проверка этого файла его не открывает. */
vi.mock('../features/settings/FaqScreen', () => ({
  FaqScreen: () => { throw new Error('FAQ a căzut') },
}))

const SHELL: ShellModel = {
  identity: null,
  clinic: { name: 'Clinica Test', mark: '', logo_topbar: '' },
  runtime: { version: '9.9.9', tz: 'Europe/Chisinau' },
  nav: {
    active: 'set',
    items: [{ key: 'set', href: '/admin/settings', icon: 'home', label: 'Setări' }],
    sync: [],
    foot_title: '',
  },
  signals: {
    tamper: { shown: false, html: '' },
    split: { shown: false, html: '' },
    slot: { shown: false, html: '' },
    setup: { shown: false, html: '' },
  },
  frame: {
    sub: 'setări', crumbs: [], rail: false, bell: null, sec_warn: '', update: '', msg: '',
    feedback: { email: 'x@y.md', href: 'mailto:x@y.md' }, today: '2026-09-24',
  },
}

function node(screen: string, params: Record<string, string> = {}, shell: ShellModel | null = null): MountNode {
  return { screen, params, shell }
}

function open(url: string, n: MountNode) {
  const router = createMemoryRouter(appRoutes(n), { initialEntries: [url] })
  return render(<App router={router} />)
}

/** Адрес-образец маршрута: каждый `:параметр` заменён числом. */
const sample = (path: string) => path.replace(/:[a-z_]+/g, '7')

/** Какой маршрут таблицы выиграл на адресе — самый глубокий в совпадении. */
function winner(url: string): string | undefined {
  return matchRoutes(appRoutes(node('x')), url)?.at(-1)?.route.path
}

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
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

  it('визит: номер берётся из параметра пути appt_id, а не из ключа узла aid', () => {
    get.mockReturnValueOnce(new Promise(() => {}))
    open('/admin/visit/42', node('visit', { aid: '999', back: '/admin/all' }))
    expect(get).toHaveBeenCalledWith(expect.stringMatching(/^\/visits\/42\?/), expect.anything())
  })

  it('адрес, которого роутер не знает: экран называется по имени и ведёт на старую страницу', () => {
    open('/admin/fisa', node('fisa'))
    expect(screen.getByRole('alert').textContent).toContain('«fisa»')
    expect((screen.getByRole('link') as HTMLAnchorElement).getAttribute('href')).toContain('?ui=legacy')
  })

  it('роутер и сервер разошлись: чужой экран НЕ рисуется, расхождение слышно', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    open('/admin/week', node('stats'))
    expect(screen.getByRole('alert').textContent).toContain('«stats»')
    expect(get).not.toHaveBeenCalled()
    expect(err.mock.calls.flat().join(' ')).toContain('schedule_week')
  })

  it('упавший экран оставляет оболочку на месте и ведёт на старую страницу', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    open('/admin/settings/faq', node('settings_faq', {}, SHELL))
    expect(screen.getByRole('alert').textContent).toContain('nu a putut fi afișat')
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Registrul Clinicii')
    expect(screen.getByTitle('Setări')).toBeTruthy()
  })
})
