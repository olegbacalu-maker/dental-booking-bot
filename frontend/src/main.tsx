/**
 * Точка входа React-клиента.
 *
 * Монтируется в страницу движка: сервер отдаёт один узел
 *   <div id="root" data-screen="имя-экрана" data-params="…" data-shell="…"></div>
 * ОТДАТЬ ли React этот адрес, решает по-прежнему СЕРВЕР — флаг в clinic.json
 * (§29) и `?ui=legacy`: включение экрана не требует пересборки, потому что оба
 * интерфейса лежат в одном бинарнике. КАКОЙ экран рисовать, с B2 решает роутер
 * по адресу, а `data-screen` остаётся свидетелем (см. `Screen` в App.tsx).
 *
 * ⛔ Тема, иконки и тексты сообщений — серверные (§7), React их потребляет.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter } from 'react-router'
import { App, appRoutes } from './app/App'
import { readShell } from './layouts/shell'
import './app/app.css'

const host = document.getElementById('root')

if (!host) {
  // Экран, который сервер ещё не отдал React, — это норма, а не поломка:
  // большинство страниц пока рисует Python. Молча выходим.
  console.debug('DentPilot: #root отсутствует — страница серверная')
} else {
  const screen = host.dataset.screen ?? 'unknown'
  // Параметры экрана (id врача и т. п.) сервер кладёт в data-params JSON-ом.
  let params: Record<string, string> = {}
  try {
    params = JSON.parse(host.dataset.params ?? '{}') as Record<string, string>
  } catch {
    console.error('DentPilot: data-params не разбирается', host.dataset.params)
  }
  // Внутри узла сервер оставил заглушку «интерфейс не загрузился» со
  // ссылкой на старую страницу (layout.react_mount). Раз мы здесь — бандл
  // загрузился; заглушку убираем сами, чтобы React монтировался в пустой узел.
  // ⭐ B1: модель оболочки приезжает ИНЛАЙНОМ, атрибутом того же узла. `null`
  // значит, что каркас ещё печатает сервер — тогда App рисует один экран.
  const shell = readShell(host)
  host.replaceChildren()
  // ⚠️ Загрузчиков у маршрутов пока нет, и поэтому первый кадр СИНХРОННЫЙ:
  // роутер инициализирован сразу, оболочка рисуется без пустого промежутка.
  // Появится загрузчик — первый кадр станет ждать его, и это решается там же.
  const router = createBrowserRouter(appRoutes({ screen, params, shell }))
  createRoot(host).render(
    <StrictMode>
      <App router={router} />
    </StrictMode>,
  )
}
