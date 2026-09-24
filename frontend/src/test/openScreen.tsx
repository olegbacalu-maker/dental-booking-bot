import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { screenRoute, type RouteLoad } from '../hooks/useRouteLoad'

/**
 * Открыть экран в проверке ТЕМ ЖЕ маршрутом, что и в App.tsx (`screenRoute`):
 * загрузчик, первый кадр на время ожидания и параметры пути. Экран на
 * загрузчике голым компонентом не открывается — данные ему приносит роутер.
 *
 *   path — шаблон маршрута (`/admin/doctor-card/:dk`), url — открываемый адрес;
 *   navigate — куда уводить при 401 на ПЕРВОЙ загрузке (у действий — свой,
 *   через проп экрана).
 */
export function openScreen(
  path: string, url: string, element: ReactElement, load: RouteLoad<unknown>,
  navigate?: (url: string) => void,
) {
  const router = createMemoryRouter([screenRoute(path, element, load, navigate)],
    { initialEntries: [url] })
  return { router, ...render(<RouterProvider router={router} />) }
}
