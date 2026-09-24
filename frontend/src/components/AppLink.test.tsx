import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { AppLink, isAppHref } from './AppLink'

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

/** Щелчок; `true` — браузер пошёл бы по ссылке сам (действие не отменено). */
function click(el: HTMLElement, init: MouseEventInit = {}): boolean {
  let native = true
  /* Слушатель окна стоит ПОСЛЕ корня React: видит решение роутера и сам
     отменяет действие, чтобы jsdom не пытался грузить документ. */
  const spy = (e: Event) => { native = !e.defaultPrevented; e.preventDefault() }
  window.addEventListener('click', spy)
  try {
    fireEvent.click(el, { button: 0, ...init })
  } finally {
    window.removeEventListener('click', spy)
  }
  return native
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
