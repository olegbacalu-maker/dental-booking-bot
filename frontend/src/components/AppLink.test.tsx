import { act, cleanup, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { nativeClick as click } from '../test/nativeClick'
import { AppLink, isAppHref, useProseLinks } from './AppLink'

afterEach(() => cleanup())

describe('isAppHref', () => {
  it('экран из карты маршрутов — переход без перезагрузки', () => {
    expect(isAppHref('/admin/week?date=2026-09-21')).toBe(true)
    expect(isAppHref('/admin')).toBe(true)
    expect(isAppHref('/admin/patient/5/odontograma?t=11')).toBe(true)
  })

  it('не экран (выгрузка, вход, печать) и чужой origin — документом, как раньше', () => {
    expect(isAppHref('/admin/export.xlsx?from=2026-09-21&to=2026-09-21')).toBe(false)
    expect(isAppHref('/admin/login')).toBe(false)
    expect(isAppHref('/admin/patient/5/print043')).toBe(false)
    expect(isAppHref('https://example.com/admin/week')).toBe(false)
  })

  it('?ui=legacy — всегда документ: это просьба к СЕРВЕРУ отдать старую страницу', () => {
    expect(isAppHref('/admin/week?date=2026-09-21&ui=legacy')).toBe(false)
    expect(isAppHref('/admin?ui=react&ui=legacy')).toBe(false)
  })
})

/** Окно с двумя «экранами» и ссылкой; что случилось со щелчком — в ответе. */
function mount(href: string) {
  const router = createMemoryRouter([
    { path: '/admin', element: <AppLink href={href}>go</AppLink> },
    { path: '/admin/week', element: <p>week</p> },
  ], { initialEntries: ['/admin'] })
  render(<RouterProvider router={router} />)
  return router
}

describe('AppLink', () => {
  it('в разметке — тот же <a href>: адрес виден, открыть в новой вкладке можно', () => {
    mount('/admin/week?date=2026-09-21')
    expect(screen.getByRole('link').getAttribute('href')).toBe('/admin/week?date=2026-09-21')
  })

  it('простой щелчок по экрану — переход роутером, документ не грузится', async () => {
    const router = mount('/admin/week?date=2026-09-21')
    let native = true
    await act(async () => { native = click(screen.getByRole('link')) })
    expect(native).toBe(false)
    expect(router.state.location.pathname + router.state.location.search).toBe('/admin/week?date=2026-09-21')
    expect(screen.getByText('week')).toBeTruthy()
  })

  it('Ctrl-щелчок — как у обычной ссылки: решает браузер, роутер не трогает', async () => {
    const router = mount('/admin/week')
    let native = false
    await act(async () => { native = click(screen.getByRole('link'), { ctrlKey: true }) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('не экран — обычная ссылка мимо роутера, а не «такого экрана нет»', async () => {
    const router = mount('/admin/export.xlsx?from=2026-09-21&to=2026-09-21')
    let native = false
    await act(async () => { native = click(screen.getByRole('link')) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('?ui=legacy — обычная ссылка: старую страницу отдаёт сервер', async () => {
    const router = mount('/admin/week?ui=legacy')
    let native = false
    await act(async () => { native = click(screen.getByRole('link')) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe('/admin')
  })
})

/** Серверная проза с тремя ссылками: экран, старая страница, своя вкладка. */
function Prose() {
  const prose = useProseLinks()
  return (
    <div onClick={prose} dangerouslySetInnerHTML={{ __html:
      "<a href='/admin/settings/system'>versiune nouă</a> "
      + "<a href='/admin/settings/system?ui=legacy'>clasic</a> "
      + "<a href='/admin/week' target='_blank'>fereastră</a>" }} />
  )
}

function mountProse() {
  const router = createMemoryRouter([
    { path: '/admin', element: <Prose /> },
    { path: '/admin/settings/system', element: <p>system</p> },
    { path: '/admin/week', element: <p>week</p> },
  ], { initialEntries: ['/admin'] })
  render(<RouterProvider router={router} />)
  return router
}

describe('useProseLinks — ссылки в серверной прозе', () => {
  it('ссылка на экран внутри готовой разметки — переход роутером', async () => {
    const router = mountProse()
    let native = true
    await act(async () => { native = click(screen.getByText('versiune nouă')) })
    expect(native).toBe(false)
    expect(router.state.location.pathname).toBe('/admin/settings/system')
  })

  it('?ui=legacy и target=_blank в прозе — браузеру, как у обычной ссылки', async () => {
    const router = mountProse()
    let a = false
    let b = false
    await act(async () => { a = click(screen.getByText('clasic')) })
    await act(async () => { b = click(screen.getByText('fereastră')) })
    expect(a).toBe(true)
    expect(b).toBe(true)
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('Ctrl-щелчок в прозе — браузеру', async () => {
    const router = mountProse()
    let native = false
    await act(async () => { native = click(screen.getByText('versiune nouă'), { ctrlKey: true }) })
    expect(native).toBe(true)
    expect(router.state.location.pathname).toBe('/admin')
  })
})
