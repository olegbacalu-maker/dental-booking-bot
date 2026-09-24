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
import { App, appHydration, appRoutes } from './app/App'
import { readNode } from './app/doc'
import './app/app.css'

const host = document.getElementById('root')

if (!host) {
  // Экран, который сервер ещё не отдал React, — это норма, а не поломка:
  // большинство страниц пока рисует Python. Молча выходим.
  console.debug('DentPilot: #root отсутствует — страница серверная')
} else {
  // ⭐ Узел читается тем же разбором, что и документ нового адреса при
  // переходе без перезагрузки (B4, `app/doc.ts`): два разборщика одного
  // атрибута разошлись бы молча. Модель оболочки (B1) приезжает ИНЛАЙНОМ,
  // атрибутом того же узла; `null` значит, что каркас печатает сервер.
  const node = readNode(host)
  // Внутри узла сервер оставил заглушку «интерфейс не загрузился» со
  // ссылкой на старую страницу (layout.react_mount). Раз мы здесь — бандл
  // загрузился; заглушку убираем сами, чтобы React монтировался в пустой узел.
  host.replaceChildren()
  // ⚠️ Узел отдаётся роутеру ГОТОВЫМ (`appHydration`): загрузчик корня на
  // первом кадре не идёт за документом, который уже на экране, и оболочка
  // рисуется сразу. Загрузчики экранов ждут данные под своим первым кадром
  // (`hydrateFallbackElement`, B2.2).
  const router = createBrowserRouter(appRoutes(), { hydrationData: appHydration(node) })
  createRoot(host).render(
    <StrictMode>
      <App router={router} />
    </StrictMode>,
  )
}
